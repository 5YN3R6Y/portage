# Copyright: 2005 Gentoo Foundation
# Author(s): Brian Harring (ferringb@gentoo.org)
# License: GPL2
# $Id:$

# all vars that are to wind up in portage_const must have their name listed in __all__

__all__ = ["EPREFIX", "SYSCONFDIR", "PORTAGE_BASE", "portageuser", "portagegroup", "rootuser", "rootuid"]

from os import path

EPREFIX=path.normpath("@DOMAIN_PREFIX@")
SYSCONFDIR=path.normpath("@sysconfdir@")
PORTAGE_BASE=path.normpath("@PORTAGE_BASE@")
portagegroup="@portagegroup@"
portageuser="@portageuser@"
rootuser="@rootuser@"
rootuid=int("@rootuid@")
