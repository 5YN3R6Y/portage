import logging
# for an explanation on this logic, see pym/_emerge/__init__.py
import os
import sys
if os.environ.__contains__("PORTAGE_PYTHONPATH"):
	sys.path.insert(0, os.environ["PORTAGE_PYTHONPATH"])
else:
	sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "pym"))
import portage

from _emerge.AsynchronousTask import AsynchronousTask
from _emerge.unmerge import unmerge
from _emerge.UninstallFailure import UninstallFailure

class PackageUninstall(AsynchronousTask):

	__slots__ = ("ldpath_mtimes", "opts", "pkg", "scheduler", "settings")

	def _start(self):
		try:
			unmerge(self.pkg.root_config, self.opts, "unmerge",
				[self.pkg.cpv], self.ldpath_mtimes, clean_world=0,
				clean_delay=0, raise_on_error=1, scheduler=self.scheduler,
				writemsg_level=self._writemsg_level)
		except UninstallFailure, e:
			self.returncode = e.status
		else:
			self.returncode = os.EX_OK
		self.wait()

	def _writemsg_level(self, msg, level=0, noiselevel=0):

		log_path = self.settings.get("PORTAGE_LOG_FILE")
		background = self.background

		if log_path is None:
			if not (background and level < logging.WARNING):
				portage.util.writemsg_level(msg,
					level=level, noiselevel=noiselevel)
		else:
			if not background:
				portage.util.writemsg_level(msg,
					level=level, noiselevel=noiselevel)

			f = open(log_path, 'a')
			try:
				f.write(msg)
			finally:
				f.close()

