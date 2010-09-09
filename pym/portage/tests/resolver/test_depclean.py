# Copyright 2010 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

from portage.tests import TestCase
from portage.tests.resolver.ResolverPlayground import ResolverPlayground, ResolverPlaygroundTestCase

class SimpleDepcleanTestCase(TestCase):

	def testSimpleDepclean(self):
		ebuilds = {
			"dev-libs/A-1": {},
			"dev-libs/B-1": {},
			}
		installed = {
			"dev-libs/A-1": {},
			"dev-libs/B-1": {},
			}

		world = (
			"dev-libs/A",
			)

		test_cases = (
			ResolverPlaygroundTestCase(
				[],
				options = {"--depclean": True},
				success = True,
				cleanlist = ["dev-libs/B-1"]),
			)

		playground = ResolverPlayground(ebuilds=ebuilds, installed=installed, world=world)
		try:
			for test_case in test_cases:
				playground.run_TestCase(test_case)
				self.assertEqual(test_case.test_success, True, test_case.fail_msg)
		finally:
			playground.cleanup()

class DepcleanWithDepsTestCase(TestCase):

	def testDepcleanWithDeps(self):
		ebuilds = {
			"dev-libs/A-1": { "RDEPEND": "dev-libs/C" },
			"dev-libs/B-1": { "RDEPEND": "dev-libs/D" },
			"dev-libs/C-1": {},
			"dev-libs/D-1": { "RDEPEND": "dev-libs/E" },
			"dev-libs/E-1": { "RDEPEND": "dev-libs/F" },
			"dev-libs/F-1": {},
			}
		installed = {
			"dev-libs/A-1": { "RDEPEND": "dev-libs/C" },
			"dev-libs/B-1": { "RDEPEND": "dev-libs/D" },
			"dev-libs/C-1": {},
			"dev-libs/D-1": { "RDEPEND": "dev-libs/E" },
			"dev-libs/E-1": { "RDEPEND": "dev-libs/F" },
			"dev-libs/F-1": {},
			}

		world = (
			"dev-libs/A",
			)

		test_cases = (
			ResolverPlaygroundTestCase(
				[],
				options = {"--depclean": True},
				success = True,
				cleanlist = ["dev-libs/B-1", "dev-libs/D-1",
					"dev-libs/E-1", "dev-libs/F-1"]),
			)

		playground = ResolverPlayground(ebuilds=ebuilds, installed=installed, world=world)
		try:
			for test_case in test_cases:
				playground.run_TestCase(test_case)
				self.assertEqual(test_case.test_success, True, test_case.fail_msg)
		finally:
			playground.cleanup()


class DepcleanWithInstalledMaskedTestCase(TestCase):

	def testDepcleanWithInstalledMasked(self):
		"""
		Test case for bug 332719.
		emerge --declean ignores that B is masked by license and removes C.
		The next emerge -uDN world doesn't take B and installs C again.
		"""
		ebuilds = {
			"dev-libs/A-1": { "RDEPEND": "|| ( dev-libs/B dev-libs/C )" },
			"dev-libs/B-1": { "LICENSE": "TEST" },
			"dev-libs/C-1": {},
			}
		installed = {
			"dev-libs/A-1": { "RDEPEND": "|| ( dev-libs/B dev-libs/C )" },
			"dev-libs/B-1": { "LICENSE": "TEST" },
			"dev-libs/C-1": {},
			}

		world = (
			"dev-libs/A",
			)

		test_cases = (
			ResolverPlaygroundTestCase(
				[],
				options = {"--depclean": True},
				success = True,
				#cleanlist = ["dev-libs/C-1"]),
				cleanlist = ["dev-libs/B-1"]),
			)

		playground = ResolverPlayground(ebuilds=ebuilds, installed=installed, world=world)
		try:
			for test_case in test_cases:
				playground.run_TestCase(test_case)
				self.assertEqual(test_case.test_success, True, test_case.fail_msg)
		finally:
			playground.cleanup()
