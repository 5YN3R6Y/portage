'''
Bazaar module Changes class submodule
'''

from repoman.modules.vcs.changes import ChangesBase
from repoman._subprocess import repoman_popen


class Changes(ChangesBase):
	'''Class object to scan and hold the resultant data
	for all changes to process.
	'''

	vcs = 'bzr'

	def __init__(self, options):
		'''Class init

		@param options: commandline options
		'''
		super(Changes, self).__init__(options)

	def _scan(self):
		'''VCS type scan function, looks for all detectable changes'''
		with repoman_popen("bzr status -S .") as f:
			bzrstatus = f.readlines()
		self.changed = [
			"./" + elem.split()[-1:][0].split('/')[-1:][0]
			for elem in bzrstatus
			if elem and elem[1:2] == "M"]
		self.new = [
			"./" + elem.split()[-1:][0].split('/')[-1:][0]
			for elem in bzrstatus
			if elem and (elem[1:2] == "NK" or elem[0:1] == "R")]
		self.removed = [
			"./" + elem.split()[-3:-2][0].split('/')[-1:][0]
			for elem in bzrstatus
			if elem and (elem[1:2] == "K" or elem[0:1] == "R")]
		# Bazaar expands nothing.

	@property
	def unadded(self):
		'''Bazzar method of getting the unadded files in the repository'''
		if self._unadded is not None:
			return self._unadded
		self._unadded = [
			"./" + elem.rstrip().split()[1].split('/')[-1:][0]
			for elem in bzrstatus
			if elem.startswith("?") or elem[0:2] == " D"]
		return self._unadded
