# Copyright 1999-2009 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

from _emerge.SpawnProcess import SpawnProcess
# for an explanation on this logic, see pym/_emerge/__init__.py
import os
import sys
if os.environ.__contains__("PORTAGE_PYTHONPATH"):
	sys.path.insert(0, os.environ["PORTAGE_PYTHONPATH"])
else:
	sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "pym"))
import portage

class BinpkgExtractorAsync(SpawnProcess):

	__slots__ = ("image_dir", "pkg", "pkg_path")

	_shell_binary = portage.const.BASH_BINARY

	def _start(self):
		# SIGPIPE handling (status 141) should be compatible with
		# assert_sigpipe_ok() that's used by the ebuild unpack() helper.
		self.args = [self._shell_binary, "-c",
			("bzip2 -dqc -- %s | tar -xp -C %s -f - ; " + \
			"p=(${PIPESTATUS[@]}) ; " + \
			"if [[ ${p[0]} != 0 && ${p[0]} != 141 ]] ; then " + \
			"echo bzip2 failed with status ${p[0]} ; exit ${p[0]} ; fi ; " + \
			"if [ ${p[1]} != 0 ] ; then " + \
			"echo tar failed with status ${p[1]} ; exit ${p[1]} ; fi ; " + \
			"exit 0 ;") % \
			(portage._shell_quote(self.pkg_path),
			portage._shell_quote(self.image_dir))]

		self.env = os.environ.copy()
		SpawnProcess._start(self)
