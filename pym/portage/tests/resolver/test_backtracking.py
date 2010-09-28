# Copyright 2010 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

from portage.tests import TestCase
from portage.tests.resolver.ResolverPlayground import ResolverPlayground, ResolverPlaygroundTestCase

class BacktrackingTestCase(TestCase):

	def testBacktracking(self):
		ebuilds = {
			"dev-libs/A-1": {},
			"dev-libs/A-2": {},
			"dev-libs/B-1": { "DEPEND": "dev-libs/A" },
			}

		test_cases = (
				ResolverPlaygroundTestCase(
					["=dev-libs/A-1", "dev-libs/B"],
					all_permutations = True,
					mergelist = ["dev-libs/A-1", "dev-libs/B-1"],
					success = True),
			)

		playground = ResolverPlayground(ebuilds=ebuilds)

		try:
			for test_case in test_cases:
				playground.run_TestCase(test_case)
				self.assertEqual(test_case.test_success, True, test_case.fail_msg)
		finally:
			playground.cleanup()


	def testHittingTheBacktrackLimit(self):
		ebuilds = {
			"dev-libs/A-1": {},
			"dev-libs/A-2": {},
			"dev-libs/B-1": {},
			"dev-libs/B-2": {},
			"dev-libs/C-1": { "DEPEND": "dev-libs/A dev-libs/B" },
			"dev-libs/D-1": { "DEPEND": "=dev-libs/A-1 =dev-libs/B-1" },
			}

		test_cases = (
				ResolverPlaygroundTestCase(
					["dev-libs/C", "dev-libs/D"],
					all_permutations = True,
					mergelist = ["dev-libs/A-1", "dev-libs/B-1", "dev-libs/C-1", "dev-libs/D-1"],
					ignore_mergelist_order = True,
					success = True),
				#This one hits the backtrack limit. Be aware that this depends on the argument order.
				ResolverPlaygroundTestCase(
					["dev-libs/D", "dev-libs/C"],
					options = { "--backtrack": 1 },
					mergelist = ["dev-libs/A-1", "dev-libs/B-1", "dev-libs/A-2", "dev-libs/B-2", "dev-libs/C-1", "dev-libs/D-1"],
					ignore_mergelist_order = True,
					slot_collision_solutions = [],
					success = False),
			)

		playground = ResolverPlayground(ebuilds=ebuilds)

		try:
			for test_case in test_cases:
				playground.run_TestCase(test_case)
				self.assertEqual(test_case.test_success, True, test_case.fail_msg)
		finally:
			playground.cleanup()


	def testBacktrackingGoodVersionFirst(self):
		"""
		When backtracking due to slot conflicts, we masked the version that has been pulled
		in first. This is not always a good idea. Mask the highest version instead.
		"""

		ebuilds = {
			"dev-libs/A-1": { "DEPEND": "=dev-libs/C-1 dev-libs/B" },
			"dev-libs/B-1": { "DEPEND": "=dev-libs/C-1" },
			"dev-libs/B-2": { "DEPEND": "=dev-libs/C-2" },
			"dev-libs/C-1": { },
			"dev-libs/C-2": { },
			}

		test_cases = (
				ResolverPlaygroundTestCase(
					["dev-libs/A"],
					mergelist = ["dev-libs/C-1", "dev-libs/B-1", "dev-libs/A-1", ],
					success = True),
			)

		playground = ResolverPlayground(ebuilds=ebuilds)

		try:
			for test_case in test_cases:
				playground.run_TestCase(test_case)
				self.assertEqual(test_case.test_success, True, test_case.fail_msg)
		finally:
			playground.cleanup()

	def testBacktrackWithoutUpdates(self):
		"""
		If --update is not given we might have to mask the old installed version later.
		"""

		ebuilds = {
			"dev-libs/A-1": { "DEPEND": "dev-libs/Z" },
			"dev-libs/B-1": { "DEPEND": ">=dev-libs/Z-2" },
			"dev-libs/Z-1": { },
			"dev-libs/Z-2": { },
			}

		installed = {
			"dev-libs/Z-1": { "USE": "" },
			}

		test_cases = (
				ResolverPlaygroundTestCase(
					["dev-libs/B", "dev-libs/A"],
					all_permutations = True,
					mergelist = ["dev-libs/Z-2", "dev-libs/B-1", "dev-libs/A-1", ],
					ignore_mergelist_order = True,
					success = True),
			)

		playground = ResolverPlayground(ebuilds=ebuilds, installed=installed)

		try:
			for test_case in test_cases:
				playground.run_TestCase(test_case)
				self.assertEqual(test_case.test_success, True, test_case.fail_msg)
		finally:
			playground.cleanup()
