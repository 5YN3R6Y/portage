

class UnusedCheck(object):
	'''Checks and reports any un-used metadata.xml use flag descriptions'''

	def __init__(self, **kwargs):
		'''UnusedCheck init function

		@param qatracker: QATracker instance
		'''
		self.qatracker = kwargs.get('qatracker')

	def check(self, **kwargs):
		'''Reports on any unused metadata.xml use descriptions

		@param xpkg: the pacakge being checked
		@param muselist: use flag list
		@param used_useflags: use flag list
		@param validity_fuse: Fuse instance
		'''
		xpkg = kwargs.get('xpkg')
		muselist = kwargs.get('muselist')
		used_useflags = kwargs.get('used_useflags')
		# check if there are unused local USE-descriptions in metadata.xml
		# (unless there are any invalids, to avoid noise)
		if kwargs.get('validity_fuse'):
			for myflag in muselist.difference(used_useflags):
				self.qatracker.add_error(
					"metadata.warning",
					"%s/metadata.xml: unused local USE-description: '%s'"
					% (xpkg, myflag))
		return {'continue': False}

	@property
	def runInFinal(self):
		'''Final scans at the package level'''
		return (True, [self.check])
