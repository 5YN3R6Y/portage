import re
from itertools import chain

# for an explanation on this logic, see pym/_emerge/__init__.py
import os
import sys
if os.environ.__contains__("PORTAGE_PYTHONPATH"):
	sys.path.insert(0, os.environ["PORTAGE_PYTHONPATH"])
else:
	sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "pym"))
import portage

from portage.cache.mappings import slot_dict_class

from _emerge.Task import Task

class Package(Task):

	__hash__ = Task.__hash__
	__slots__ = ("built", "cpv", "depth",
		"installed", "metadata", "onlydeps", "operation",
		"root_config", "type_name",
		"category", "counter", "cp", "cpv_split",
		"inherited", "iuse", "mtime",
		"pf", "pv_split", "root", "slot", "slot_atom", "use")

	metadata_keys = [
		"CHOST", "COUNTER", "DEPEND", "EAPI",
		"INHERITED", "IUSE", "KEYWORDS",
		"LICENSE", "PDEPEND", "PROVIDE", "RDEPEND",
		"repository", "PROPERTIES", "RESTRICT", "SLOT", "USE", "_mtime_",
		"EPREFIX" ]

	def __init__(self, **kwargs):
		Task.__init__(self, **kwargs)
		self.root = self.root_config.root
		self.metadata = _PackageMetadataWrapper(self, self.metadata)
		self.cp = portage.cpv_getkey(self.cpv)
		slot = self.slot
		if not slot:
			# Avoid an InvalidAtom exception when creating slot_atom.
			# This package instance will be masked due to empty SLOT.
			slot = '0'
		self.slot_atom = portage.dep.Atom("%s:%s" % (self.cp, slot))
		self.category, self.pf = portage.catsplit(self.cpv)
		self.cpv_split = portage.catpkgsplit(self.cpv)
		self.pv_split = self.cpv_split[1:]

	class _use(object):

		__slots__ = ("__weakref__", "enabled")

		def __init__(self, use):
			self.enabled = frozenset(use)

	class _iuse(object):

		__slots__ = ("__weakref__", "all", "enabled", "disabled", "iuse_implicit", "regex", "tokens")

		def __init__(self, tokens, iuse_implicit):
			self.tokens = tuple(tokens)
			self.iuse_implicit = iuse_implicit
			enabled = []
			disabled = []
			other = []
			for x in tokens:
				prefix = x[:1]
				if prefix == "+":
					enabled.append(x[1:])
				elif prefix == "-":
					disabled.append(x[1:])
				else:
					other.append(x)
			self.enabled = frozenset(enabled)
			self.disabled = frozenset(disabled)
			self.all = frozenset(chain(enabled, disabled, other))

		def __getattribute__(self, name):
			if name == "regex":
				try:
					return object.__getattribute__(self, "regex")
				except AttributeError:
					all = object.__getattribute__(self, "all")
					iuse_implicit = object.__getattribute__(self, "iuse_implicit")
					# Escape anything except ".*" which is supposed
					# to pass through from _get_implicit_iuse()
					regex = (re.escape(x) for x in chain(all, iuse_implicit))
					regex = "^(%s)$" % "|".join(regex)
					regex = regex.replace("\\.\\*", ".*")
					self.regex = re.compile(regex)
			return object.__getattribute__(self, name)

	def _get_hash_key(self):
		hash_key = getattr(self, "_hash_key", None)
		if hash_key is None:
			if self.operation is None:
				self.operation = "merge"
				if self.onlydeps or self.installed:
					self.operation = "nomerge"
			self._hash_key = \
				(self.type_name, self.root, self.cpv, self.operation)
		return self._hash_key

	def __lt__(self, other):
		if other.cp != self.cp:
			return False
		if portage.pkgcmp(self.pv_split, other.pv_split) < 0:
			return True
		return False

	def __le__(self, other):
		if other.cp != self.cp:
			return False
		if portage.pkgcmp(self.pv_split, other.pv_split) <= 0:
			return True
		return False

	def __gt__(self, other):
		if other.cp != self.cp:
			return False
		if portage.pkgcmp(self.pv_split, other.pv_split) > 0:
			return True
		return False

	def __ge__(self, other):
		if other.cp != self.cp:
			return False
		if portage.pkgcmp(self.pv_split, other.pv_split) >= 0:
			return True
		return False

_all_metadata_keys = set(x for x in portage.auxdbkeys \
	if not x.startswith("UNUSED_"))
_all_metadata_keys.discard("CDEPEND")
_all_metadata_keys.update(Package.metadata_keys)

_PackageMetadataWrapperBase = slot_dict_class(_all_metadata_keys)

class _PackageMetadataWrapper(_PackageMetadataWrapperBase):
	"""
	Detect metadata updates and synchronize Package attributes.
	"""

	__slots__ = ("_pkg",)
	_wrapped_keys = frozenset(
		["COUNTER", "INHERITED", "IUSE", "SLOT", "USE", "_mtime_"])

	def __init__(self, pkg, metadata):
		_PackageMetadataWrapperBase.__init__(self)
		self._pkg = pkg
		self.update(metadata)

	def __setitem__(self, k, v):
		_PackageMetadataWrapperBase.__setitem__(self, k, v)
		if k in self._wrapped_keys:
			getattr(self, "_set_" + k.lower())(k, v)

	def _set_inherited(self, k, v):
		if isinstance(v, basestring):
			v = frozenset(v.split())
		self._pkg.inherited = v

	def _set_iuse(self, k, v):
		self._pkg.iuse = self._pkg._iuse(
			v.split(), self._pkg.root_config.iuse_implicit)

	def _set_slot(self, k, v):
		self._pkg.slot = v

	def _set_use(self, k, v):
		self._pkg.use = self._pkg._use(v.split())

	def _set_counter(self, k, v):
		if isinstance(v, basestring):
			try:
				v = long(v.strip())
			except ValueError:
				v = 0
		self._pkg.counter = v

	def _set__mtime_(self, k, v):
		if isinstance(v, basestring):
			try:
				v = long(v.strip())
			except ValueError:
				v = 0
		self._pkg.mtime = v
