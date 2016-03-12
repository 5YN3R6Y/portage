'''
Git module Changes class submodule
'''

from repoman.modules.vcs.changes import ChangesBase
from repoman._subprocess import repoman_popen
from repoman._portage import portage
from portage import os
from portage.package.ebuild.digestgen import digestgen


class Changes(ChangesBase):
	'''Class object to scan and hold the resultant data
	for all changes to process.
	'''

	vcs = 'git'

	def __init__(self, options, repo_settings):
		'''Class init

		@param options: commandline options
		'''
		super(Changes, self).__init__(options, repo_settings)

	def _scan(self):
		'''VCS type scan function, looks for all detectable changes'''
		with repoman_popen(
			"git diff-index --name-only "
			"--relative --diff-filter=M HEAD") as f:
			changed = f.readlines()
		self.changed = ["./" + elem[:-1] for elem in changed]
		del changed

		with repoman_popen(
			"git diff-index --name-only "
			"--relative --diff-filter=A HEAD") as f:
			new = f.readlines()
		self.new = ["./" + elem[:-1] for elem in new]
		del new

		with repoman_popen(
			"git diff-index --name-only "
			"--relative --diff-filter=D HEAD") as f:
			removed = f.readlines()
		self.removed = ["./" + elem[:-1] for elem in removed]
		del removed

	@property
	def unadded(self):
		'''VCS method of getting the unadded files in the repository'''
		if self._unadded is not None:
			return self._unadded
		# get list of files not under version control or missing
		with repoman_popen("git ls-files --others") as f:
			unadded = f.readlines()
		self._unadded = ["./" + elem[:-1] for elem in unadded]
		del unadded
		return self._unadded

	def digest_regen(self, myupdates, myremoved, mymanifests, scanner, broken_changelog_manifests):
		if broken_changelog_manifests:
			for x in broken_changelog_manifests:
				self.repoman_settings["O"] = os.path.join(self.repo_settings.repodir, x)
				digestgen(mysettings=self.repoman_settings, myportdb=self.repo_settings.portdb)
