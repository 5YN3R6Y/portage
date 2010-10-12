# Copyright 2010 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

__all__ = (
	'MaskManager',
)

from portage import os
from portage.dep import ExtendedAtomDict, match_from_list, _repo_separator, _slot_separator
from portage.util import append_repo, grabfile_package, stack_lists
from portage.versions import cpv_getkey

class MaskManager(object):

	def __init__(self, repositories, profiles, abs_user_config,
		user_config=True, strict_umatched_removal=False):
		self._punmaskdict = ExtendedAtomDict(list)
		self._pmaskdict = ExtendedAtomDict(list)

		#Read profile/package.mask form every repo.
		#Repositories inherit masks from their parent profiles and
		#are able to remove mask from them with -atoms.
		#Such a removal affects only the current repo, but not the parent.
		#Add ::repo specs to every atom to make sure atoms only affect
		#packages from the current repo.

		repo_pkgmasklines = []
		for repo in repositories.repos_with_profiles():
			lines = []
			repo_lines = grabfile_package(os.path.join(repo.location, "profiles", "package.mask"), \
				recursive=1, remember_source_file=True, verify_eapi=True)
			for master in repo.masters:
				master_lines = grabfile_package(os.path.join(master.location, "profiles", "package.mask"), \
					recursive=1, remember_source_file=True, verify_eapi=True)
				lines.append(stack_lists([master_lines, repo_lines], incremental=1,
					remember_source_file=True, warn_for_unmatched_removal=True,
					strict_warn_for_unmatched_removal=strict_umatched_removal))
			if not repo.masters:
				lines.append(stack_lists([repo_lines], incremental=1,
					remember_source_file=True, warn_for_unmatched_removal=True,
					strict_warn_for_unmatched_removal=strict_umatched_removal))
			repo_pkgmasklines.extend(append_repo(stack_lists(lines), repo.name, remember_source_file=True))

		repo_pkgunmasklines = []
		for repo in repositories.repos_with_profiles():
			repo_lines = grabfile_package(os.path.join(repo.location, "profiles", "package.unmask"), \
				recursive=1, remember_source_file=True, verify_eapi=True)
			lines = stack_lists([repo_lines], incremental=1, \
				remember_source_file=True, warn_for_unmatched_removal=True,
				strict_warn_for_unmatched_removal=strict_umatched_removal)
			repo_pkgmasklines.extend(append_repo(lines, repo.name, remember_source_file=True))

		#Read package.mask form the user's profile. Stack them in the end
		#to allow profiles to override masks from their parent profiles.
		profile_pkgmasklines = []
		profile_pkgunmasklines = []
		# PREFIX LOCAL: Prefix has unmasks for stuff in profiles/package.mask
		# If we don't consider the repomasks here, those unmasks are
		# lost, causing lots of issues (e.g. Portage being masked)
		# for minimal/concentrated code change, empty repo_pkgmasklines here
		# such that they don't count double
		repo_pkgmasklines = []
		repo_pkgunmasklines = []
		all_profiles = []
		for repo in repositories.repos_with_profiles():
			all_profiles.append(os.path.join(repo.location, "profiles"))
		all_profiles.extend(profiles)
		for x in all_profiles:
			profile_pkgmasklines.append(grabfile_package(
				os.path.join(x, "package.mask"), recursive=1, remember_source_file=True, verify_eapi=True))
			profile_pkgunmasklines.append(grabfile_package(
				os.path.join(x, "package.unmask"), recursive=1, remember_source_file=True, verify_eapi=True))
		profile_pkgmasklines = stack_lists(profile_pkgmasklines, incremental=1, \
			remember_source_file=True, warn_for_unmatched_removal=True,
			strict_warn_for_unmatched_removal=strict_umatched_removal)
		profile_pkgunmasklines = stack_lists(profile_pkgunmasklines, incremental=1, \
			remember_source_file=True, warn_for_unmatched_removal=True,
			strict_warn_for_unmatched_removal=strict_umatched_removal)
		# PREFIX LOCAL

		#Read /etc/portage/package.mask. Don't stack it to allow the user to
		#remove mask atoms from everywhere with -atoms.
		user_pkgmasklines = []
		user_pkgunmasklines = []
		if user_config:
			user_pkgmasklines = grabfile_package(
				os.path.join(abs_user_config, "package.mask"), recursive=1, \
				allow_wildcard=True, allow_repo=True, remember_source_file=True, verify_eapi=False)
			user_pkgunmasklines = grabfile_package(
				os.path.join(abs_user_config, "package.unmask"), recursive=1, \
				allow_wildcard=True, allow_repo=True, remember_source_file=True, verify_eapi=False)

		#Stack everything together. At this point, only user_pkgmasklines may contain -atoms.
		#Don't warn for unmatched -atoms here, since we don't do it for any other user config file.
		pkgmasklines = stack_lists([repo_pkgmasklines, profile_pkgmasklines, user_pkgmasklines], \
			incremental=1, remember_source_file=True, warn_for_unmatched_removal=False, ignore_repo=True)
		pkgunmasklines = stack_lists([repo_pkgunmasklines, profile_pkgunmasklines, user_pkgunmasklines], \
			incremental=1, remember_source_file=True, warn_for_unmatched_removal=False, ignore_repo=True)

		for x, source_file in pkgmasklines:
			self._pmaskdict.setdefault(x.cp, []).append(x)

		for x, source_file in pkgunmasklines:
			self._punmaskdict.setdefault(x.cp, []).append(x)

		for d in (self._pmaskdict, self._punmaskdict):
			for k, v in d.items():
				d[k] = tuple(v)

	def getMaskAtom(self, cpv, slot, repo):
		"""
		Take a package and return a matching package.mask atom, or None if no
		such atom exists or it has been cancelled by package.unmask. PROVIDE
		is not checked, so atoms will not be found for old-style virtuals.

		@param cpv: The package name
		@type cpv: String
		@param slot: The package's slot
		@type slot: String
		@rtype: String
		@return: An matching atom string or None if one is not found.
		"""

		cp = cpv_getkey(cpv)
		mask_atoms = self._pmaskdict.get(cp)
		if mask_atoms:
			pkg = "".join((cpv, _slot_separator, slot))
			if repo:
				pkg = "".join((pkg, _repo_separator, repo))
			pkg_list = [pkg]
			unmask_atoms = self._punmaskdict.get(cp)
			for x in mask_atoms:
				if not match_from_list(x, pkg_list):
					continue
				if unmask_atoms:
					for y in unmask_atoms:
						if match_from_list(y, pkg_list):
							return None
				return x
		return None
