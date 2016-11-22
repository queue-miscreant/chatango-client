#!/usr/bin/env python3
#linkopen.py
'''
Library for opening links. Allows extension through wrappers
Open links by file extension, site pattern, or lambda truth
evaluation.
Althought this does not import .display (or any other module in the package),
open_link expects an instance of display.Main as its first argument.
'''
import re
import os #for stupid stdout/err hack
from threading import Thread
import subprocess
from webbrowser import open_new_tab

__all__ =	["LINK_RE","getLinks","recentLinks","getDefaults","parseLinks"
			,"opener","open_link","daemonize","images","videos","browser"]

#canonical link regex
LINK_RE = re.compile("(https?://.+?\\.[^`\\s]+)[`\\s]")
_POST_FORMAT_RE = re.compile(r"\.(\w+)[&/\?]?")
IMG_PATH = "feh"
MPV_PATH = "mpv"
_lastlinks = []

class LinkException(Exception):
	'''Exception for errors in client.linkopen'''

def getLinks():
	return list(_lastlinks)

def recentLinks():
	'''Get links, but sans protocol and in reverse'''
	return [i.replace("http://","").replace("https://","")\
		 for i in reversed(_lastlinks)]

def clearLinks():
	'''Clear links'''
	_lastlinks.clear()

def getDefaults():
	'''
	Get the names of the default functions.
	These are hopefully descriptive enough
	'''
	return ["default"] + [i.__name__ for i in open_link._defaults]

def parseLinks(raw,prepend = False):
	'''
	Add links to lastlinks. Prepend argument for adding links backwards,
	like with historical messages.
	'''
	global _lastlinks
	newLinks = []
	#look for whole word links starting with http:// or https://
	#don't add the same link twice
	for i in LINK_RE.findall(raw+" "):
		if i not in newLinks:
			newLinks.append(i)
	if prepend:
		newLinks.reverse()
		_lastlinks = newLinks + _lastlinks
	else:
		_lastlinks += newLinks

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
		ext = _POST_FORMAT_RE.findall(link)
		if not default:
			#check from ext
			if len(ext) > 1:
				run = self._exts.get(ext[-1].lower())
				if run:
					return run(client,link,ext[-1])
			#check for patterns
			for i,j in self._sites.items():
				if 1+link.find(i):
					return j(client,link)
			#check for lambdas
			for i,j in zip(self._lambdas,self._lambdalut):
				if i(link):
					return j(client,link)
			return self._defaults[default](client,link)
		else:
			return self._defaults[default-1](client,link)

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
			self(args[0])
			return
		if args[0] not in ["default","extension","pattern","lambda"]:
			raise LinkException("invalid first argument of linkopen.opener {}".format(args[0]))
		self._type = args[0]
		self._argument = args[1]

	def __call__(self,func):
		#gross if statements
		if self._type == "default":
			open_link._defaults.append(func)
		elif self._type == "extension":
			open_link._exts[self._argument] = func
		elif self._type == "pattern":
			open_link._sites[self._argument] = func
		elif self._type == "lambda":
			open_link.link_opener.lambdas.append(self._argument)
			open_link.link_opener.lambdalut.append(func)
		#allow stacking wrappers
		return func

def daemonize(func):
	'''Build a function that starts a daemon thread over the given function'''
	def ret(*args,**kwargs):
		funcThread = Thread(target = func, args = args ,kwargs = kwargs)
		funcThread.daemon = True
		funcThread.start()
	ret.__name__ = func.__name__
	ret.__doc__ = func.__doc__
	return ret

#PREDEFINED OPENERS-------------------------------------------------------------------------------------
#start and daemonize feh (or replaced image viewing program)
@opener("extension","jpeg")
@opener("extension","jpg")
@opener("extension","jpg:large")
@opener("extension","png")
@opener("extension","png:large")
@daemonize
def images(main, link, ext):
	main.newBlurb("Displaying image... ({})".format(ext))
	args = [IMG_PATH, link]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		displayProcess.communicate()
	except:
		main.newBlurb("No viewer %s found"%FEH_PATH)
	
@opener("extension","webm")
@opener("extension","mp4")
@opener("extension","gif")
@daemonize
def videos(main, link, ext):
	'''Start and daemonize mpv (or replaced video playing program)'''
	main.newBlurb("Playing video... ({})".format(ext))
	args = [MPV_PATH, link, "--pause"]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		displayProcess.communicate()
	except:
		main.newBlurb("No player %s found"%MPV_PATH)

@opener
def browser(main, link):
	'''Open new tab'''
	main.newBlurb("Opened new tab")
	#magic code to output stderr to /dev/null
	savout = os.dup(1)	#get another header for stdout
	saverr = os.dup(2)	#get another header for stderr
	os.close(1)		#close stdout briefly because open_new_tab doesn't pipe stdout to null
	os.close(2)
	os.open(os.devnull, os.O_RDWR)	#open devnull for writing
	try:
		open_new_tab(link)	#do thing
	finally:
		os.dup2(savout, 1)	#reopen stdout
		os.dup2(saverr, 2)
