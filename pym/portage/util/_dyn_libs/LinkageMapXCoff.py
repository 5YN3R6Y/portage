# Copyright 1998-2011 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

import errno
import logging
import subprocess

import portage
from portage import _encodings
from portage import _os_merge
from portage import _unicode_decode
from portage import _unicode_encode
from portage.cache.mappings import slot_dict_class
from portage.exception import CommandNotFound
from portage.localization import _
from portage.util import getlibpaths
from portage.util import grabfile
from portage.util import normalize_path
from portage.util import writemsg_level
from portage.const import EPREFIX, BASH_BINARY
from portage.util._dyn_libs.LinkageMapELF import LinkageMapELF

class LinkageMapXCoff(LinkageMapELF):

	"""Models dynamic linker dependencies."""

	_needed_aux_key = "NEEDED.XCOFF.1"

	class _ObjectKey(LinkageMapELF._ObjectKey):

		def __init__(self, obj, root):
			LinkageMapELF._ObjectKey.__init__(self, obj, root)

		def _generate_object_key(self, obj, root):
			"""
			Generate object key for a given object.

			@param object: path to a file
			@type object: string (example: '/usr/bin/bar')
			@rtype: 2-tuple of types (long, int) if object exists. string if
				object does not exist.
			@return:
				1. 2-tuple of object's inode and device from a stat call, if object
					exists.
				2. realpath of object if object does not exist.

			"""

			os = _os_merge

			try:
				_unicode_encode(obj,
					encoding=_encodings['merge'], errors='strict')
			except UnicodeEncodeError:
				# The package appears to have been merged with a 
				# different value of sys.getfilesystemencoding(),
				# so fall back to utf_8 if appropriate.
				try:
					_unicode_encode(obj,
						encoding=_encodings['fs'], errors='strict')
				except UnicodeEncodeError:
					pass
				else:
					os = portage.os

			abs_path = os.path.join(root, obj.lstrip(os.sep))
			try:
				object_stat = os.stat(abs_path)
			except OSError:
				# Use the realpath as the key if the file does not exists on the
				# filesystem.
				return os.path.realpath(abs_path)
			# Return a tuple of the device and inode, as well as the basename,
			# because of hardlinks the device and inode might be identical.
			return (object_stat.st_dev, object_stat.st_ino, os.path.basename(abs_path.rstrip(os.sep)))

		def file_exists(self):
			"""
			Determine if the file for this key exists on the filesystem.

			@rtype: Boolean
			@return:
				1. True if the file exists.
				2. False if the file does not exist or is a broken symlink.

			"""
			return isinstance(self._key, tuple)

	class _LibGraphNode(_ObjectKey):
		__slots__ = ("alt_paths",)

		def __init__(self, obj, root):
			LinkageMapXCoff._ObjectKey.__init__(self, obj, root)
			self.alt_paths = set()

		def __str__(self):
			return str(sorted(self.alt_paths))

	def rebuild(self, exclude_pkgs=None, include_file=None,
		preserve_paths=None):
		"""
		Raises CommandNotFound if there are preserved libs
		and the scanelf binary is not available.

		@param exclude_pkgs: A set of packages that should be excluded from
			the LinkageMap, since they are being unmerged and their NEEDED
			entries are therefore irrelevant and would only serve to corrupt
			the LinkageMap.
		@type exclude_pkgs: set
		@param include_file: The path of a file containing NEEDED entries for
			a package which does not exist in the vardbapi yet because it is
			currently being merged.
		@type include_file: String
		@param preserve_paths: Libraries preserved by a package instance that
			is currently being merged. They need to be explicitly passed to the
			LinkageMap, since they are not registered in the
			PreservedLibsRegistry yet.
		@type preserve_paths: set
		"""

		os = _os_merge
		root = self._root
		root_len = len(root) - 1
		self._clear_cache()
		self._defpath.update(getlibpaths(self._root))
		libs = self._libs
		obj_properties = self._obj_properties

		lines = []

		# Data from include_file is processed first so that it
		# overrides any data from previously installed files.
		if include_file is not None:
			for line in grabfile(include_file):
				lines.append((include_file, line))

		aux_keys = [self._needed_aux_key]
		can_lock = os.access(os.path.dirname(self._dbapi._dbroot), os.W_OK)
		if can_lock:
			self._dbapi.lock()
		try:
			for cpv in self._dbapi.cpv_all():
				if exclude_pkgs is not None and cpv in exclude_pkgs:
					continue
				needed_file = self._dbapi.getpath(cpv,
					filename=self._needed_aux_key)
				for line in self._dbapi.aux_get(cpv, aux_keys)[0].splitlines():
					lines.append((needed_file, line))
		finally:
			if can_lock:
				self._dbapi.unlock()

		# have to call scanelf for preserved libs here as they aren't 
		# registered in NEEDED.XCOFF.1 files
		plibs = set()
		if preserve_paths is not None:
			plibs.update(preserve_paths)
		if self._dbapi._plib_registry and \
			self._dbapi._plib_registry.hasEntries():
			for cpv, items in \
				self._dbapi._plib_registry.getPreservedLibs().items():
				if exclude_pkgs is not None and cpv in exclude_pkgs:
					# These preserved libs will either be unmerged,
					# rendering them irrelevant, or they will be
					# preserved in the replacement package and are
					# already represented via the preserve_paths
					# parameter.
					continue
				plibs.update(items)
		if plibs:
			for x in plibs:
				args = [BASH_BINARY, "-c", ':'
					+ '; member="' + x + '"'
					+ '; archive=${member}'
					+ '; if [[ ${member##*/} == .*"["*"]" ]]'
					+ '; then member=${member%/.*}/${member##*/.}'
						 + '; archive=${member%[*}'
					+ '; fi'
					+ '; member=${member#${archive}}'
					+ '; [[ -r ${archive} ]] || chmod a+r "${archive}"'
					+ '; eval $(aixdll-query "${archive}${member}" FILE MEMBER FLAGS FORMAT RUNPATH DEPLIBS)'
					+ '; [[ -n ${member} ]] && needed=${FILE##*/} || needed='
					+ '; for deplib in ${DEPLIBS}'
					+ '; do eval deplib=${deplib}'
					   + '; if [[ ${deplib} != "." && ${deplib} != ".." ]]'
					   + '; then needed="${needed}${needed:+,}${deplib}"'
					   + '; fi'
					+ '; done'
					+ '; [[ -n ${MEMBER} ]] && MEMBER="[${MEMBER}]"'
					+ '; [[ " ${FLAGS} " == *" SHROBJ "* ]] && soname=${FILE##*/}${MEMBER} || soname='
					+ '; echo "${FORMAT##* }${FORMAT%%-*};${FILE#${ROOT%/}}${MEMBER};${soname};${RUNPATH};${needed}"'
					+ '; [[ -z ${member} && -n ${MEMBER} ]] && echo "${FORMAT##* }${FORMAT%%-*};${FILE#${ROOT%/}};${FILE##*/};;"'
				]
			try:
				proc = subprocess.Popen(args, stdout=subprocess.PIPE)
			except EnvironmentError as e:
				if e.errno != errno.ENOENT:
					raise
				raise CommandNotFound(args[0])
			else:
				for l in proc.stdout:
					try:
						l = _unicode_decode(l,
							encoding=_encodings['content'], errors='strict')
					except UnicodeDecodeError:
						l = _unicode_decode(l,
							encoding=_encodings['content'], errors='replace')
						writemsg_level(_("\nError decoding characters " \
							"returned from aixdll-query: %s\n\n") % (l,),
							level=logging.ERROR, noiselevel=-1)
					l = l.rstrip("\n")
					if not l:
						continue
					fields = l.split(";")
					if len(fields) < 5:
						writemsg_level(_("\nWrong number of fields " \
							"returned from aixdll-query: %s\n\n") % (l,),
							level=logging.ERROR, noiselevel=-1)
						continue
					fields[1] = fields[1][root_len:]
					plibs.discard(fields[1])
					lines.append(("aixdll-query", ";".join(fields)))
				proc.wait()

		if plibs:
			# Preserved libraries that did not appear in the bash
			# aixdll-query code output.  This is known to happen with
			# statically linked libraries.  Generate dummy lines for
			# these, so we can assume that every preserved library has
			# an entry in self._obj_properties.  This is important in
			# order to prevent findConsumers from raising an unwanted
			# KeyError.
			for x in plibs:
				lines.append(("plibs", ";".join(['', x, '', '', ''])))

		for location, l in lines:
			l = l.rstrip("\n")
			if not l:
				continue
			fields = l.split(";")
			if len(fields) < 5:
				writemsg_level(_("\nWrong number of fields " \
					"in %s: %s\n\n") % (location, l),
					level=logging.ERROR, noiselevel=-1)
				continue
			arch = fields[0]

			def as_contentmember(obj):
				if obj.endswith("]"):
					if obj.find("/") >= 0:
						return obj[:obj.rfind("/")] + "/." + obj[obj.rfind("/")+1:]
					return "." + obj
				return obj

			obj = as_contentmember(fields[1])
			soname = as_contentmember(fields[2])
			path = set([normalize_path(x) \
				for x in filter(None, fields[3].replace(
				"${ORIGIN}", os.path.dirname(obj)).replace(
				"$ORIGIN", os.path.dirname(obj)).split(":"))])
			needed = [as_contentmember(x) for x in fields[4].split(",") if x]

			obj_key = self._obj_key(obj)
			indexed = True
			myprops = obj_properties.get(obj_key)
			if myprops is None:
				indexed = False
				myprops = (arch, needed, path, soname, set())
				obj_properties[obj_key] = myprops
			# All object paths are added into the obj_properties tuple.
			myprops[4].add(obj)

			# Don't index the same file more that once since only one
			# set of data can be correct and therefore mixing data
			# may corrupt the index (include_file overrides previously
			# installed).
			if indexed:
				continue

			arch_map = libs.get(arch)
			if arch_map is None:
				arch_map = {}
				libs[arch] = arch_map
			if soname:
				soname_map = arch_map.get(soname)
				if soname_map is None:
					soname_map = self._soname_map_class(
						providers=set(), consumers=set())
					arch_map[soname] = soname_map
				soname_map.providers.add(obj_key)
			for needed_soname in needed:
				soname_map = arch_map.get(needed_soname)
				if soname_map is None:
					soname_map = self._soname_map_class(
						providers=set(), consumers=set())
					arch_map[needed_soname] = soname_map
				soname_map.consumers.add(obj_key)

	def getSoname(self, obj):
		"""
		Return the soname associated with an object.

		@param obj: absolute path to an object
		@type obj: string (example: '/usr/bin/bar')
		@rtype: string
		@return: soname as a string

		"""
		if not self._libs:
			self.rebuild()
		if isinstance(obj, self._ObjectKey):
			obj_key = obj
			if obj_key not in self._obj_properties:
				raise KeyError("%s not in object list" % obj_key)
			return self._obj_properties[obj_key][3]
		if obj not in self._obj_key_cache:
			raise KeyError("%s not in object list" % obj)
		return self._obj_properties[self._obj_key_cache[obj]][3]

