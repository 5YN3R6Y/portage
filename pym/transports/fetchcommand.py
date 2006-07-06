# Copyright 2006 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2
# $Id: portage_const.py 3761 2006-07-02 19:40:56Z genone $

from transports import Fetcher, FetchException, uriparse
from portage_exec import spawn_bash
import sys, os

class BasicCommandFetcher(Fetcher):
	def __init__(self, name, protos, fetchcommand, resumecommand):
		self._name = name
		self._protos = protos
		self._fetchcommand = fetchcommand
		self._resumecommand = resumecommand
	
	def getCommand(self, uri, destination, resume):
		if os.path.isfile(destination):
			destdir = os.path.dirname(destination)
			destfilename = os.path.basename(destination)
		else:
			destdir = destination
			destfilename = os.path.basename(uri)
		
		if resume and os.path.isfile(os.path.join(destdir, destfilename)):
			mycommand = self._resumecommand
		else:
			mycommand = self._fetchcommand
		
		mycommand = mycommand.replace("${URI}", uri)
		mycommand = mycommand.replace("${FILE}", destfilename)
		mycommand = mycommand.replace("${DISTDIR}", destdir)
		
		return mycommand
	
	def _fetch(self, uri, destination, resume=False, fd=sys.stdout):
		return spawn_bash(self.getCommand(uri, destination, resume), fd_pipes={0:0,1:fd,2:fd})

class FancyCommandFetcher(BasicCommandFetcher):
	def __init__(self, name, protos, fetchcommand, resumecommand, settings):
		super(FancyCommandFetcher, self).__init__(name, protos, fetchcommand, resumecommand)
		self._settings = settings
	
	def _fetch(self, uri, destination, resume=False, fd=sys.stdout):
		mycommand = self.getCommand(uri, destination, resume)
		spawn_keywords = {"env": self._settings.environ()}
		if "userfetch" in self._settings.features and \
				os.getuid() == 0 and portage_gid and portage_uid:
			spawn_keywords.update({
								"uid"    : portage_uid,
								"gid"    : portage_gid,
								"groups" : [portage_gid],
								"umask"  : 002})
		if self._settings.selinux_enabled():
			import selinux
			con = selinux.getcontext()
			con = cont.replace(con, self._settings["PORTAGE_T"], self._settings["PORTAGE_FETCH_T"])
			selinux.setexec(con)

		myret = spawn_bash(mycommand, **spawn_keywords)

		if self._settings.selinux_enabled():
			selinux.setexec(None)

		if myret != 0:
			raise FetchException()

		return myret

def get_commands(settings, key):
	fetchcmd = settings["FETCHCOMMAND"+key]
	try:
		resumecmd = settings["RESUMECOMMAND"+key]
	# anticipate for new potential config() behavior
	except KeyError:
		resumecmd = fetchcmd
	if resumecmd == "":
		resumecmd = fetchcmd

	return (fetchcmd, resumecmd)

CMD_VARNAME="FETCHCOMMAND"

def init(settings, set_preferred=False):
	for k in settings.keys():
		if k.startswith(CMD_VARNAME):
			key = k[len(CMD_VARNAME):]
			commands = get_commands(settings, key)
			
			if key == "":
				protos = ["http", "ftp"]
				name = "Command"
			elif key[0] == "_":
				protos = [key[1:].lower()]
				name = "Command"+key[1].upper()+key[2:].lower()
			else:
				continue
			
			fetcher = FancyCommandFetcher(name, protos, commands[0], commands[1], settings)
			for p in protos:
				m = __import__("transports.protocols."+p, [], [], "protocol")
				m.protocol.addFetcher(fetcher)
				if set_preferred:
					m.protocol.setPreferredFetcher(fetcher.getName())
