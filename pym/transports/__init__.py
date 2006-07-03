# Copyright 2006 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2
# $Id: portage_const.py 3483 2006-06-10 21:40:40Z genone $

import os, sys
from transports.protocols import Protocol
from transports.protocols.mirror import MirrorProtocol

class FetchException(Exception):
	pass

class Fetcher(object):
	_protos = []
	
	def fetch(self, uri, destination, resume=False, cleanup=False, fd=sys.stdout):
		proto = uriparse(uri)[0]
		if proto not in self._protos:
			raise Exception("Fetcher %s doesn't support protocol %s" % (self._name, proto))
		try:
			return self._fetch(uri, destination, resume)
		except FetchException, e:
			if cleanup and os.path.exists(destination):
				os.unlink(destination)

	def _fetch(self, uri, destination, resume=False, fd=sys.stdout):
		""" This method has to be overridden by inheriting classes """
		raise NotImplementedError()

	def getName(self):
		return self._name

# urlparse.urlparse() is broken unfortunately as it only handles "supported" 
# protocols, and "mirror://" isn't supported
def uriparse(uri):
	proto_sep_pos = uri.find("://")
	if proto_sep_pos < 0:
		proto = "file"
		loc = os.path.dirname(uri)
		name = os.path.basename(uri)
	else:
		loc_sep_pos = uri.find("/", proto_sep_pos+3)
	
		proto = uri[:proto_sep_pos]
		loc = uri[proto_sep_pos+3:loc_sep_pos]
		name = uri[loc_sep_pos+1:]
	
	return (proto, loc, name)

def fetch(uri, destination, mirrorlist=[], resume=False, cleanup=False, failover=False, fd=sys.stdout):
	proto, loc, name = uriparse(uri)
	p = Protocol.getProtocol(proto)
	if len(mirrorlist) > 0:
		mirrorlist.append(proto+"://"+loc+"/"+os.dirname(name))
		mirrormap = {"_internal": mirrorlist}
		filename = os.path.basename(name)
		mirroruri = "mirror://_internal/"+filename
		mp = MirrorProtocol(mirrormap)
		return mp.fetch(mirroruri, destination, fd, resume, cleanup, failover, fd)
	else:
		return p.fetch(uri, destination, resume, cleanup, failover, fd)

def init(settings, prefer_commands=True):
	# TODO: replace with a generic and extensible solution
	import transports.fetchcommand as fcmd
	fcmd.init(settings, set_preferred=prefer_commands)

	import transports.file
	# file module has auto-init
	
	import transports.protocols.mirror as mirror
	mirror.init(settings)
