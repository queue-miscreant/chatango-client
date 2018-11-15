#!/usr/bin/env python3
#linkopen.py
'''
Library for opening links. Allows extension through wrappers
Open links by file extension, site pattern, or lambda truth
evaluation.
Althought this does not import .display (or any other module in the package),
open_link expects an instance of display.Main as its first argument.

All openers are made into coroutines so that create_subprocess_exec can be
yielded from. open_link creates a task in the Main instance's loop
'''
import re
import os	#for stupid stdout/err hack
import sys	#cygwin
import asyncio
from subprocess import DEVNULL

IMG_ARGS = ["feh"]
MPV_ARGS = ["mpv","--pause"]
if sys.platform == "cygwin":
	#from what I can tell, there are no good command line image viewers
	#that can handle links in windows, so I'm defaulting images to browser
	#vlc and mpv exist for windows though, so just change client.linkopen.MPV_ARGS
	IMG_ARGS = []
	if os.getenv("BROWSER") is None:
		#prioritize cygstart for windows users
		os.environ["BROWSER"] = os.path.pathsep.join(["cygstart","chrome",
			"firefox","waterfox","palemoon"])

import webbrowser

__all__ =	["getDefaults","getExtension","opener","open_link","images","videos","browser"]

#extension recognizing regex
_POST_FORMAT_RE = re.compile(r"\.(\w+)[&/\?]?")

class LinkException(Exception):
	'''Exception for errors in client.linkopen'''

def getDefaults():
	'''
	Get the names of the default functions.
	These are hopefully descriptive enough
	'''
	return ["default"] + [i.__name__ for i in open_link._defaults]

def getExtension(link):
	try:
		return _POST_FORMAT_RE.findall(link)[-1]
	except NameError: return

#---------------------------------------------------------------
class open_link:
	'''Open a link with the declared openers'''
	#storage for openers
	_defaults = []
	_exts = {}
	_sites = {}
	_lambdas = []
	_lambdalut = []

	def __init__(self,client,link,default = 0):
		ext = getExtension(link)
		if not default:
			#check from ext
			if ext:
				run = self._exts.get(ext.lower())
				if run:
					client.loop.create_task(run(client,link,ext))
					return
			#check for patterns
			for i,j in self._sites.items():
				found = False
				#compiled regex
				if isinstance(i,type(_POST_FORMAT_RE)):
					found = i.search(link)
				elif isinstance(i,str):
					found = 1+link.find(i)
				if found: 
					client.loop.create_task(j(client,link))
					return
			#check for lambdas
			for i,j in zip(self._lambdas,self._lambdalut):
				if i(link):
					client.loop.create_task(j(client,link))
					return
			client.loop.create_task(self._defaults[default](client,link))
			return
		client.loop.create_task(self._defaults[default-1](client,link))

	@classmethod
	def extensionOpeners(self):
		return self._exts.keys()

class opener:
	'''
	An opener for a link. With no arguments, sets a default opener.
	Otherwise, the first argument must be "default", "extension", "pattern",
	or "lambda". Extension openers open links of a certain extension, pattern
	openers match a website, and lambdas open a link when a corresponding
	callable returns true.
	'''
	def __init__(self,*args):
		if len(args) == 1 and callable(args[0]):
			self._type = "default"
			self.func = self(args[0])
			return
		if args[0] not in ["default","extension","pattern","lambda"]:
			raise LinkException("invalid first argument of linkopen.opener {}".format(args[0]))
		self._type = args[0]
		self._argument = args[1]

	def __call__(self,*args,**kw):
		#gross if statements
		if hasattr(self,"func"):
			return self.func(*args,**kw)
		#coroutinize the function unless it already is one
		#(i.e. with stacked wrappers or async def)
		func = args[0]
		if not asyncio.iscoroutinefunction(func):
			func = asyncio.coroutine(func)

		if self._type == "default":
			open_link._defaults.append(func)
		elif self._type == "extension":
			open_link._exts[self._argument] = func
		elif self._type == "pattern":
			open_link._sites[self._argument] = func
		elif self._type == "lambda":
			open_link._lambdas.append(self._argument)
			open_link._lambdalut.append(func)
		#allow stacking wrappers
		return func

#PREDEFINED OPENERS-------------------------------------------------------------
@opener("extension","jpeg")
@opener("extension","jpg")
@opener("extension","jpg:large")
@opener("extension","png")
@opener("extension","png:large")
def images(main, link, ext):
	'''Start feh (or replaced image viewer) in main.loop'''
	global IMG_ARGS
	if not IMG_ARGS:
		ret = yield from browser(main,link)
		return ret
	main.newBlurb("Displaying image... (%s)" % ext)
	args = IMG_ARGS + [link]
	try:
		yield from asyncio.create_subprocess_exec(*args
			,stdin=DEVNULL,stdout=DEVNULL,stderr=DEVNULL,loop=main.loop)
	except FileNotFoundError:
		main.newBlurb("Image viewer %s not found, defaulting to browser" % \
			IMG_ARGS[0])
		IMG_ARGS.clear()
		ret = yield from browser(main,link)
		return ret
	
@opener("extension","webm")
@opener("extension","mp4")
@opener("extension","gif")
def videos(main, link, ext):
	'''Start mpv (or replaced video player) in main.loop'''
	global MPV_ARGS
	if not MPV_ARGS:
		ret = yield from browser(main,link)
		return ret
	main.newBlurb("Playing video... ({})".format(ext))
	args = MPV_ARGS + [link]
	try:
		yield from asyncio.create_subprocess_exec(*args
			,stdin=DEVNULL,stdout=DEVNULL,stderr=DEVNULL,loop=main.loop)
	except FileNotFoundError:
		main.newBlurb("Video player %s not found, defaulting to browser" % \
			MPV_ARGS[0])
		MPV_ARGS.clear()
		ret = yield from browser(main,link)
		return ret

@opener
def browser(main, link):
	'''Open new tab without webbrowser outputting to stdout/err'''
	main.newBlurb("Opened new tab")
	#get file descriptors for stdout
	fdout, fderr =  sys.stdout.fileno(), sys.stderr.fileno()
	savout, saverr = os.dup(fdout), os.dup(fderr)	#get new file descriptors
	#close output briefly because open_new_tab prints garbage
	os.close(fdout)	
	if fdout != fderr: os.close(fderr)
	try:
		webbrowser.open_new_tab(link)
	finally:	#reopen stdout/stderr
		os.dup2(savout, fdout)	
		os.dup2(saverr, fderr)
