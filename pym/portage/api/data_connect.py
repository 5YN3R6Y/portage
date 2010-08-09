#!/usr/bin/python
#
# Copyright 1998-2010 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

"""Portage API data connection for consumer apps.  """

import os.path

import portage
from portage import pkgsplit
from portage.api.settings import settings
from portage.dep import Atom
from portage import manifest
from portage.api.flag import get_flags
from portage.api.properties import Properties
from portage.util import writemsg_level, grabfile


def get_path(cpv, file=None, vardb=True, root=None):
	"""Returns a path to the specified category/package-version in 
	either the vardb or portdb
	
	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@type file: string
	@param file:
	@param vardb: bool, defaults to  True
	@type root: string
	@param root: tree root to use
	@rtype string
	@return '/path/to/file'
	"""
	if root is None:
		root = settings.settings["ROOT"]
	if vardb:
		return settings.vardb[root].getpath(cpv, file)
	else:
		if '/' not in cpv:
			return ''
		try:
			dir,ovl = settings.portdb[root].findname2(cpv)
		except:
			dir = ''
		return dir


def xmatch(root, *args, **kwargs):
	"""Pass arguments on to portage's caching match function.
	xmatch('match-all',package-name) returns all ebuilds of <package-name> in a list,
	xmatch('match-visible',package-name) returns non-masked ebuilds,
	xmatch('match-list',package-name,mylist=list) checks for <package-name> in <list>
	There are more possible arguments.
	package-name may be, for example:
	   gnome-base/control-center            ebuilds for gnome-base/control-center
	   control-center                       ebuilds for gnome-base/control-center
	   >=gnome-base/control-center-2.8.2    only ebuilds with version >= 2.8.2
	
	@type root: string
	@param root: tree root to use
	@param args:  The arument to pass to the dbapi.xmatch()
	@param kwargs: the extra arguments to pass to dbapi.xmatch()
	@rtype list
	@return: list of matches
	"""
	results  =  settings.portdb[root].xmatch(*args, **kwargs)
	return results


def get_versions(cp, include_masked=True, root=None):
	"""Returns all available ebuilds for the package
	
	@type cp: string
	@param cp:  'cat/pkg'
	@type root: string
	@param root: tree root to use
	@rtype
	@return
	"""
	if root is None:
		root = settings.settings["ROOT"]
	# Note: this is slow, especially when include_masked is false
	criterion = include_masked and 'match-all' or 'match-visible'
	results = xmatch(root, criterion, str(cp))
	#writemsg_level(
	#	"DATA_CONNECT: get_versions(); criterion = %s, package = %s, results = %s" %(str(criterion),cp,str(results)),
	#  level=logging.DEBUG)
	return  results


def get_hard_masked(cp, root=None):
	"""
	
	@type cp: string
	@param cp:  'cat/pkg'
	@type root: string
	@param root: tree root to use
	@rtype tuple
	@return (hard_masked_nocheck, hardmasked)
	"""
	if root is None:
		root = settings.settings["ROOT"]
	cp = str(cp)
	hardmasked = []
	try: # newer portage
		pmaskdict = settings.portdb[root].settings.pmaskdict[cp]
	except KeyError:
		pmaskdict = {}
	for x in pmaskdict:
		m = xmatch("match-all", x)
		for n in m:
			if n not in hardmasked:
				hardmasked.append(n)
	hard_masked_nocheck = hardmasked[:]
	try: # newer portage
		punmaskdict = settings.portdb[root].settings.punmaskdict[cp]
	except KeyError:
		punmaskdict = {}
	for x in punmaskdict:
		m = xmatch(root, "match-all",x)
		for n in m:
			while n in hardmasked: hardmasked.remove(n)
	return hard_masked_nocheck, hardmasked


def get_installed_files(cpv, root=None):
	"""Get a list of installed files for an ebuild, assuming it has
	been installed.

	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@type root: string
	@param root: tree root to use
	@rtype list of strings
	"""
	if root is None:
		root = settings.settings["ROOT"]
	cat, pv = portage.versions.catsplit(cpv)
	db = portage.dblink(cat, pv, root,
			settings.settings, treetype="vartree",
			vartree=settings.vardb[root])
	contents = db.getcontents()
	if not contents:
		return ["None"]
	return sorted(contents)


def best(versions):
	"""returns the best version in the list of supplied versions
	
	@type versions: list of strings
	@param versions: a list of cpv's
	@rtype str
	"""
	return portage.best(versions)


def get_best_ebuild(cp, root=None):
	"""returns the best available cpv
	
	@type cp: string
	@param cp: 'cat/pkg'
	@type root: string
	@param root: tree root to use
	@rtype str
	"""
	if root is None:
		root = settings.settings["ROOT"]
	return xmatch(root, "bestmatch-visible", cp)


def get_dep_ebuild(dep, root=None):
	"""Progresively checks for available ebuilds that match the dependency.
	returns what it finds as up to three options.
	
	@type dep: string
	@param dep: a valid dependency
	@type root: string
	@param root: tree root to use
	@rtype set
	@return  best_ebuild, keyworded_ebuild, masked_ebuild
	"""
	if root is None:
		root = settings.settings["ROOT"]
	#writemsg_level("DATA_CONNECT: get_dep_ebuild(); dep = " + dep, level=logging.DEBUG)
	best_ebuild = keyworded_ebuild = masked_ebuild = ''
	best_ebuild = xmatch(root, "bestmatch-visible", dep)
	if best_ebuild == '':
		#writemsg_level("DATA_CONNECT: get_dep_ebuild(); checking masked packages", level=logging.DEBUG)
		atomized_dep = Atom(dep)
		hardmasked_nocheck, hardmasked = get_hard_masked(atomized_dep.cpv)
		matches = xmatch(root, "match-all", dep)[:]
		masked_ebuild = best(matches)
		keyworded = []
		for m in matches:
			if m not in hardmasked:
				keyworded.append(m)
		keyworded_ebuild = best(keyworded)
	#writemsg_level(
		#"DATA_CONNECT: get_dep_ebuild(); ebuilds = " + str([best_ebuild, keyworded_ebuild, masked_ebuild]),
		#level=logging.DEBUG)
	return best_ebuild, keyworded_ebuild, masked_ebuild


def get_virtual_dep(atom):
	"""Returns the first (prefered) resolved virtual dependency
	if there is more than 1 possible resolution
	
	@param atom: dependency string
	@rtpye: string
	@return 'cat/pkg-ver'
	"""
	return settings.settings.getvirtuals()[atom][0]


def get_masking_status(cpv):
	"""Gets the current masking status
	
	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@rtype str
	"""
	try:
		status = portage.getmaskingstatus(cpv)
	except KeyError:
		status = ['deprecated']
	return status


def get_masking_reason(cpv, root=None):
	"""Strips trailing \n from, and returns the masking reason given by portage
	
	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@type root: string
	@param root: tree root to use
	@rtype str
	"""
	if root is None:
		root = settings.settings["ROOT"]
	reason, location = portage.getmaskingreason(
		cpv, settings=settings.settings, portdb=settings.portdb[root],
		return_location=True)
	if not reason:
		reason = 'No masking reason given.'
		status =  get_masking_status(cpv)
		if 'profile' in status:
			reason = "Masked by the current profile."
			status.remove('profile')
		if status:
			reason += " from " + ', '.join(status)
	if location != None:
		reason += "in file: " + location
	if reason.endswith("\n"):
		reason = reason[:-1]
	return reason


def get_size(cpv, formatted_string=True, root=None):
	""" Returns size of package to fetch.
	
	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@param formatted_string: defaults to True
	@type root: string
	@param root: tree root to use
	@rtype str, or int
	"""
	if root is None:
		root = settings.settings["ROOT"]
	#This code to calculate size of downloaded files was taken from /usr/bin/emerge - BB
	#writemsg_level( "DATA_CONNECT: get_size; cpv = " + cpv, level=logging.DEBUG)
	total = [0,'']
	ebuild = settings.portdb[root].findname(cpv)
	pkgdir = os.path.dirname(ebuild)
	mf = manifest.Manifest(pkgdir, settings.settings["DISTDIR"])
	iuse, final_use = get_flags(cpv, final_setting=True, root=root)
	#writemsg_level( "DATA_CONNECT: get_size; Attempting to get fetchlist final use= " + str(final_use),
		#level=logging.DEBUG)
	try:
		fetchlist = settings.portdb[root].getFetchMap(cpv, set(final_use))
		#writemsg_level( "DATA_CONNECT: get_size; fetchlist= " +str(fetchlist), level=logging.DEBUG)
		#writemsg_level( "DATA_CONNECT: get_size; mf.getDistfilesSize()", level=logging.DEBUG)
		total[0] = mf.getDistfilesSize(fetchlist)
		if formatted_string:
			total_str = str(total[0]/1024)
			#writemsg_level( "DATA_CONNECT: get_size; total_str = " + total_str, level=logging.DEBUG)
			count=len(total_str)
			while (count > 3):
				count-=3
				total_str=total_str[:count]+","+total_str[count:]
			total[1]=total_str+" kB"
	except KeyError, e:
		total[1] = "Unknown (missing digest)"
		total[0] = 0
		#writemsg_level( "DATA_CONNECT: get_size; Exception: " + str(e),  level=logging.DEBUG)
		#writemsg_level( "DATA_CONNECT: get_size; cpv: " + str(cpv), level=logging.DEBUG)
		#writemsg_level( "DATA_CONNECT: get_size; fetchlist = " + str(fetchlist), level=logging.DEBUG)
	#writemsg_level( "DATA_CONNECT: get_size; returning total[1] = " + total[1], level=logging.DEBUG)
	if formatted_string:
		return total[1]
	return total[0]


def get_properties(cpv, want_dict=False, root=None):
	"""Get all ebuild variables in one chunk.
	
	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@type root: string
	@param root: tree root to use
	@rtype
	@return all properties of cpv
	"""
	if root is None:
		root = settings.settings["ROOT"]
	prop_dict = None
	if settings.portdb[root].cpv_exists(cpv): # if in portage tree
		try:
			#writemsg_level(" * DATA_CONNECT: get_properties()", level=logging.DEBUG)
			prop_dict = dict(zip(settings.keys, settings.portdb[root].aux_get(cpv, portage.auxdbkeys)))
		except IOError, e: # Sync being performed may delete files
			#writemsg_level(" * DATA_CONNECT: get_properties(): IOError: %s" % str(e), level=logging.DEBUG)
			pass
		except Exception, e:
			#writemsg_level(" * DATA_CONNECT: get_properties(): Exception: %s" %str( e), level=logging.DEBUG)
			pass
	else:
		if settings.vardb[root].cpv_exists(cpv): # elif in installed pkg tree
			prop_dict = dict(zip(settings.keys, settings.vardb[root].aux_get(cpv, portage.auxdbkeys)))
	if want_dict:
		# return an empty dict instead of None 
		return prop_dict or {}
	return Properties(prop_dict)


def is_overlay(cpv, root=None): # lifted from gentoolkit
	"""Returns true if the package is in an overlay.
	
	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@type root: string
	@param root: tree root to use
	@rtype bool
	"""
	if root is None:
		root = settings.settings["ROOT"]
	try:
		dir,ovl = settings.portdb[root].findname2(cpv)
	except:
		return False
	return ovl != settings.portdir


def get_overlay(cpv, root=None):
	"""Returns a portage overlay id
	
	@type cpv: string
	@param cpv: 'cat/pkg-ver'
	@type root: string
	@param root: tree root to use
	@rtype str
	@return portage overlay id. or 'Deprecated?
	'"""
	if root is None:
		root = settings.settings["ROOT"]
	if '/' not in cpv:
		return ''
	try:
		dir,ovl = settings.portdb[root].findname2(cpv)
	except:
		ovl = 'Deprecated?'
	return ovl


def get_overlay_name(ovl_path=None, cpv=None, root=None):
	"""Returns the overlay name for either the overlay path or the cpv of a pkg
	
	@param ovl_path: optional portage overlay path
	@param cpv: optional cat/pkg-ver string
	@type root: string
	@param root: tree root to use
	@rtype str
	"""
	if root is None:
		root = settings.settings["ROOT"]
	if not ovl_path and cpv:
		ovl_path= get_overlay(cpv, root)
	name = None
	name = settings.portdb[root].getRepositoryName(ovl_path)
	return name or "????"


def get_repositories(root=None):
	"""Returns a list of all repositories for root
	"""
	if root is None:
		root = settings.settings["ROOT"]
	return self.portdb[root].getRepositories()


def get_system_pkgs(root=None): # lifted from gentoolkit
	"""Returns a tuple of lists, first list is resolved system packages,
	second is a list of unresolved packages.
	
	@type root: string
	@param root: tree root to use
	@rtype: tuple 
	@return (resolved, unresolved) pkg lists
	"""
	if root is None:
		root = settings.settings["ROOT"]
	pkglist = settings.settings.packages
	resolved = []
	unresolved = []
	for x in pkglist:
		cpv = x.strip()
		pkg = get_best_ebuild(cpv, root)
		if pkg:
			try:
				resolved.append(Atom(pkg).cp)
			except:
				resolved.append(pkgsplit(pkg)[0])
		else:
			unresolved.append(pkgsplit(cpv)[0])
	return (resolved, unresolved)


def get_allnodes(root=None):
	"""Returns a list of all availabe cat/pkg's available from the tree
	and configured overlays. Subject to masking.
	
	@type root: string
	@param root: tree root to use
	@rtpye: list
	@return: ['cat/pkg1', 'cat/pkg2',...]
	"""
	if root is None:
		root = settings.settings["ROOT"]
	return settings.portdb[root].cp_all()


def get_installed_list(root=None):
	"""Returns a list of all installed cat/pkg-ver available from the tree
	and configured overlays. Subject to masking.
	
	@type root: string
	@param root: tree root to use
	@rtpye: list
	@return: ['cat/pkg1-ver', 'cat/pkg2-ver',...]
	"""
	if root is None:
		root = settings.settings["ROOT"]
	return settings.vardb[root].cpv_all()


def get_cp_all(root=None, vardb=False, categories=None, trees=None):
	"""
	This returns a list of all keys in our tree or trees
	@param categories: optional list of categories to search or 
		defaults to settings.portdb.settings.categories
	@param trees: optional list of trees to search the categories in or
		defaults to settings.portdb.porttrees
	@rtype list of [cat/pkg,...]
	"""
	if root is None:
		root = settings.settings["ROOT"]
	if vardb:
		cp_all = settings.vardb[root].cp_all()
		if categories:
			d= {}
			for cp in cp_all:
				cp_split = catpkgsplit(cp)
			return sorted(d)
		return cp_all
	return settings.portdb[root].cp_all(categories, trees)


def get_cp_list(root=None, cp=None, trees=None):
	if root is None:
		root = settings.settings["ROOT"]
	return settings.portdb[root].cp_list(cp, trees)


def findLicensePath(license_name, root=None):
	if root is None:
		root = settings.settings["ROOT"]
	return settings.portdb[root].findLicensePath(license_name)


def getFetchMap(pkg, useflags=None, tree=None):
	"""
	Get the SRC_URI metadata as a dict which maps each file name to a
	set of alternative URIs.

	@param mypkg: cpv for an ebuild
	@type pkg: String
	@param useflags: a collection of enabled USE flags, for evaluation of
		conditionals
	@type useflags: set, or None to enable all conditionals
	@param tree: The canonical path of the tree in which the ebuild
		is located, or None for automatic lookup
	@type pkg: String
	@returns: A dict which maps each file name to a set of alternative
		URIs.
	@rtype: dict
	"""
	if root is None:
		root = settings.settings["ROOT"]
	return settings.portdb[root].getfetchsizes(pkg, useflags, tree)


def getfetchsizes(pkg, useflags=None, root=None):
	"""Returns a filename:size dictionnary of remaining downloads
	"""
	if root is None:
		root = settings.settings["ROOT"]
	return settings.portdb[root].getfetchsizes(pkg, useflags)


def cpv_exists(cpv, root=None):
	"""Tells us whether an actual ebuild exists on disk (no masking)
	"""
	if root is None:
		root = settings.settings["ROOT"]
	return settings.portdb[root].cpv_exists(cpv)
