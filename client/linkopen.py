#!/usr/bin/env python3
#linkopen.py
'''
Library for opening links. Allows extension through wrappers
Open links by file extension, site pattern, or lambda truth
evaluation.
Althought this does not import .display (or any other module in the package),
open_link expects an instance of base.Screen as its first argument.

All openers are made into coroutines so that create_subprocess_exec can be
yielded from. open_link creates a task in the Screen instance's loop
'''
import re
from time import time
import os	#for stupid stdout/err hack
import sys	#cygwin
import asyncio
from http.client import HTTPException	#for catching IncompleteRead
from urllib.error import HTTPError
from urllib.request import urlopen
from subprocess import DEVNULL

IMG_ARGS = ["feh"]
MPV_ARGS = ["mpv", "--pause"]
if sys.platform == "cygwin":
	#from what I can tell, there are no good command line image viewers
	#that can handle links in windows, so I'm defaulting images to browser
	#vlc and mpv exist for windows though, so just change client.linkopen.MPV_ARGS
	IMG_ARGS = []
	if os.getenv("BROWSER") is None:
		#prioritize cygstart for windows users
		os.environ["BROWSER"] = os.path.pathsep.join(["cygstart", "chrome",
			"firefox", "waterfox", "palemoon"])

import webbrowser

__all__ =	["LINK_RE", "get_defaults", "get_extension", "opener", "open_link"
	, "images", "videos", "browser"]

#extension recognizing regex
_NO_QUERY_FRAGMENT_RE =	re.compile(r"[^?#]+(?=.*)")
_EXTENSION_RE = re.compile(r"\.(\w+)[&/\?]?")
LINK_RE = re.compile("(https?://.+?\\.[^`\\s]+)")
#opengraph regex
OG_RE = re.compile(b"<meta (?:name|property)=\"og:(\\w+)\" content=\"(.+?)\""
	, re.MULTILINE)

class LinkException(Exception):
	'''Exception for errors in client.linkopen'''

def get_defaults():
	'''
	Get the names of the default functions. These are hopefully
	descriptive enough
	'''
	return [i.__name__ for i in open_link.defaults]

def get_extension(link):
	'''
	Get the extension (png, jpg) that a particular link ends with
	Extension must be recognized by open_link.
	'''
	try:
		#try at first with the GET variable
		extensions = _EXTENSION_RE.findall(link)
		if extensions and extensions[-1].lower() in open_link.exts:
			return extensions[-1].lower()
		#now trim it off
		link = _NO_QUERY_FRAGMENT_RE.match(link)[0]
		extensions = _EXTENSION_RE.findall(link)
		if extensions and extensions[-1].lower() in open_link.exts:
			return extensions[-1].lower()
	except (IndexError, NameError):
		pass
	return ""

async def urlopen_async(link, loop=None):
	'''Awaitable urllib.request.urlopen; run in a thread pool executor'''
	if loop is None:
		loop = asyncio.get_event_loop()
	try:
		ret = await loop.run_in_executor(None, lambda: urlopen(link))
		return ret
	except (HTTPError, HTTPException):
		return ""

async def get_opengraph(link, loop=None) -> dict:
	'''Awaitable opengraph data'''
	html = await urlopen_async(link, loop=loop)
	meta = OG_RE.findall(html.read())
	return {i.decode(): j.decode() for i, j in meta}

#---------------------------------------------------------------
class open_link:
	'''Open a link with the declared openers'''
	#storage for openers
	defaults = []
	exts = {}
	sites = {}
	lambdas = []
	lambda_lut = []

	_visited = []

	def __init__(self, client, link, default=0):
		#append to visited links
		if link not in self._visited:
			self._visited.append(link)

		#don't need to step through opener types if default is set
		if default:
			client.loop.create_task(self.defaults[default-1](client, link))
			return

		ext = get_extension(link)
		ext_opener = self.exts.get(ext)
		#check from ext
		if ext_opener is not None:
			client.loop.create_task(ext_opener(client, link, ext))
			return
		#check for patterns
		for i, j in self.sites.items():
			found = False
			#compiled regex
			if isinstance(i, re.Pattern):
				found = i.search(link)
			elif isinstance(i, str):
				found = 1+link.find(i)
			if found:
				client.loop.create_task(j(client, link))
				return
		#check for lambdas
		for i, j in zip(self.lambdas, self.lambda_lut):
			if i(link):
				client.loop.create_task(j(client, link))
				return
		client.loop.create_task(self.defaults[default](client, link))

	@classmethod
	def extension_openers(cls):
		return cls.exts.keys()

	@classmethod
	def is_visited(cls, link):
		return link in cls._visited

class opener:
	'''
	An opener for a link. With no arguments, sets a default opener.
	Otherwise, the first argument must be "default", "extension", "pattern",
	or "lambda". Extension openers open links of a certain extension, pattern
	openers match a website, and lambdas open a link when a corresponding
	callable returns true.
	'''
	def __init__(self, *args):
		if len(args) == 1 and callable(args[0]):
			self._type = "default"
			self.func = self(args[0])
			return
		if args[0] not in ["default", "extension", "pattern", "lambda"]:
			raise LinkException("invalid first argument of " + \
				"linkopen.opener {}".format(args[0]))
		self._type = args[0]
		self._argument = args[1]

	def __call__(self, *args, **kw):
		#gross if statements
		if hasattr(self, "func"):
			return self.func(*args, **kw)
		#coroutinize the function unless it already is one
		#(i.e. with stacked wrappers or async def)
		func = args[0]
		if not asyncio.iscoroutinefunction(func):
			func = asyncio.coroutine(func)

		if self._type == "default":
			open_link.defaults.append(func)
		elif self._type == "extension":
			open_link.exts[self._argument] = func
		elif self._type == "pattern":
			open_link.sites[self._argument] = func
		elif self._type == "lambda":
			open_link.lambdas.append(self._argument)
			open_link.lambda_lut.append(func)
		#allow stacking wrappers
		return func

#PREDEFINED OPENERS-------------------------------------------------------------
@opener("extension", "jpeg")
@opener("extension", "jpg")
@opener("extension", "jpg:large")
@opener("extension", "png")
@opener("extension", "png:large")
async def images(main, link, ext):
	'''Start feh (or replaced image viewer) in main.loop'''
	if not IMG_ARGS:
		return await browser(main, link)
	main.blurb.push("Displaying image... (%s)" % ext)
	args = IMG_ARGS + [link]
	try:
		await asyncio.create_subprocess_exec(*args
			, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, loop=main.loop)
	except FileNotFoundError:
		main.blurb.push("Image viewer %s not found, defaulting to browser" % \
			IMG_ARGS[0])
		IMG_ARGS.clear()
		ret = await browser(main, link)
		return ret

@opener("extension", "webm")
@opener("extension", "mp4")
@opener("extension", "gif")
async def videos(main, link, ext):
	'''Start mpv (or replaced video player) in main.loop'''
	if not MPV_ARGS:
		return await browser(main, link)
	main.blurb.push("Playing video... ({})".format(ext))
	args = MPV_ARGS + [link]
	try:
		await asyncio.create_subprocess_exec(*args
			, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, loop=main.loop)
	except FileNotFoundError:
		main.blurb.push("Video player %s not found, defaulting to browser" % \
			MPV_ARGS[0])
		MPV_ARGS.clear()
		ret = await browser(main, link)
		return ret

@opener
async def browser(main, link):
	'''Open new tab without webbrowser outputting to stdout/err'''
	main.blurb.push("Opened new tab")
	#get file descriptors for stdout
	fdout, fderr = sys.stdout.fileno(), sys.stderr.fileno()
	savout, saverr = os.dup(fdout), os.dup(fderr)	#get new file descriptors
	#close output briefly because open_new_tab prints garbage
	os.close(fdout)
	if fdout != fderr:
		os.close(fderr)
	try:
		webbrowser.open_new_tab(link)
	finally:	#reopen stdout/stderr
		os.dup2(savout, fdout)
		os.dup2(saverr, fderr)
