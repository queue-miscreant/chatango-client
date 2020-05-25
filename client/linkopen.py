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
import os	#cygwin, stupid stdout/err hack
import sys	#same
import re	#link patterns, link pattern openers
import asyncio		#subprocess spawning
import traceback	#link opening failures
from http.client import HTTPException	#for catching IncompleteRead
from urllib.error import HTTPError
from urllib.request import urlopen
from html import unescape
from subprocess import DEVNULL

from .input import ConfirmOverlay

IMG_ARGS = ["feh"]
MPV_ARGS = ["mpv", "--pause"]
if sys.platform in ("win32", "cygwin"):
	#by default, BROWSER does not include `cygstart`, which is a cygwin program
	#that will (for links) open things in the default system browser
	if os.getenv("BROWSER") is None:
		#prioritize cygstart for windows users
		os.environ["BROWSER"] = os.path.pathsep.join(["cygstart", "chrome"
			, "firefox", "waterfox", "palemoon"])

import webbrowser #pylint: disable=wrong-import-position, wrong-import-order

__all__ =	["LINK_RE", "get_defaults", "get_extension", "opener", "open_link"
	, "images", "videos", "browser"]

#extension recognizing regex
_NO_QUERY_FRAGMENT_RE =	re.compile(r"[^?#]+(?=.*)")
_EXTENSION_RE = re.compile(r"\.(\w+)[&/\?]?")
LINK_RE = re.compile("(https?://.+?\\.[^`\\s]+)")
#opengraph regex
OG_RE = re.compile(b"<meta\\s+(?:name|property)=\"og:(\\w+)\"\\s+" \
	b"content=\"(.+?)\"", re.MULTILINE)

class LinkException(Exception):
	'''Exception for errors in client.linkopen'''

def get_defaults():
	'''
	Get the names of the default functions. These are hopefully
	descriptive enough
	'''
	return [i.__name__ for i in opener.defaults]

def get_extension(link):
	'''
	Get the extension (png, jpg) that a particular link ends with
	Extension must be recognized by open_link.
	'''
	try:
		#try at first with the GET variable
		extensions = _EXTENSION_RE.findall(link)
		if extensions and extensions[-1].lower() in opener.exts:
			return extensions[-1].lower()
		#now trim it off
		link = _NO_QUERY_FRAGMENT_RE.match(link)[0]
		extensions = _EXTENSION_RE.findall(link)
		if extensions and extensions[-1].lower() in opener.exts:
			return extensions[-1].lower()
	except (IndexError, NameError):
		pass
	return ""

async def urlopen_async(link, loop=None):
	'''Awaitable urllib.request.urlopen; run in a thread pool executor'''
	if loop is None:
		loop = asyncio.get_event_loop()
	try:
		ret = await loop.run_in_executor(None, urlopen, link)
		return ret
	except (HTTPError, HTTPException):
		return ""

async def get_opengraph(link, *args, loop=None):
	'''
	Awaitable OpenGraph data, with HTML5 entities converted into unicode.
	If a tag repeats (like image), the value will be a list. Returns dict if no
	extra args supplied. Otherwise, for each in `*args`, return is such that
	`value1[, value2] = get_opengraph(..., key1[, key2])` formats correctly.
	'''
	html = await urlopen_async(link, loop=loop)
	if not html:
		raise Exception(f"Curl failed for {repr(link)}")

	full = {}
	for i, j in OG_RE.findall(html.read()):
		i = i.decode()
		j = unescape(j.decode())
		prev = full.get(i)
		if prev is None:
			full[i] = j
			continue
		if not isinstance(prev, list):
			full[i] = [prev]
		full[i].append(j)

	if not args:
		return full
	if len(args) == 1:
		return full[args[0]]		#never try 1-tuple assignment
	return [full[i] if i in full else None for i in args]	#tuple unpacking

class DummyScreen: #pylint: disable=too-few-public-methods
	'''Dummy class for base.Screen used by _LinkDelegator'''
	loop = property(lambda _: asyncio.get_event_loop())
	class blurb: #pylint: disable=invalid-name
		push = lambda _: None
		hold = lambda _: None
		release = lambda _: None
	def add_overlay(self, other):
		pass
	def pop_overlay(self, other):
		pass

#---------------------------------------------------------------
class _LinkDelegator: #pylint: disable=invalid-name
	'''
	Class that delegates opening links to the openers, keeps track of which
	links have been visited, and issues redraws when that updates
	'''
	warning_count = 5
	def __init__(self):
		self._visited = set()
		self._visit_redraw = []

	def __call__(self, screen, links, default=0, force=False):
		'''Open a link (or list of links) with the declared openers'''
		if screen is None:
			screen = DummyScreen()
		if not isinstance(links, list):
			links = [links]

		#limit opening too many links
		if not force and len(links) >= self.warning_count:
			ConfirmOverlay(screen, "Really open %d links? (y/n)" % len(links)
				, lambda: self(screen, links, default, True)).add()
			return

		do_redraw = False
		for link in links:
			#append to visited links
			if link not in self._visited:
				self._visited.add(link)
				do_redraw = True
			func = opener.get(link, default)
			screen.loop.create_task(self._open_safe(func, screen, link))

		if do_redraw:
			for func in self._visit_redraw:
				func()

	def visit_link(self, links):
		'''Mark links as visited without using an opener'''
		if not isinstance(links, list):
			links = [links]

		do_redraw = False
		for link in links:
			#append to visited links
			if link not in self._visited:
				self._visited.add(link)
				do_redraw = True

		if do_redraw:
			for func in self._visit_redraw:
				func()

	async def _open_safe(self, func, screen, link):
		'''Safely open a link and catch exceptions'''
		try:
			await func(screen, link)
		except Exception as exc: #pylint: disable=broad-except
			screen.blurb.push("Error opening link: " + str(exc))
			traceback.print_exc()

	def is_visited(self, link):
		'''Returns if a link has been visited'''
		return link in self._visited

	def add_redraw_method(self, func):
		'''Add function `func` to call (with no arguments) on link visit'''
		self._visit_redraw.append(func)

	def del_redraw_method(self, func):
		'''Delete redraw method `func` added with `add_redraw_method`'''
		try:
			index = self._visit_redraw.index(func)
			del self._visit_redraw[index]
		except ValueError:
			pass
open_link = _LinkDelegator() #pylint: disable=invalid-name
visit_link = open_link.visit_link #pylint: disable=invalid-name

class opener: #pylint: disable=invalid-name
	'''
	Decorator for a link opener. With no arguments, sets a default opener.
	Otherwise, the first argument must be "default", "extension", "pattern",
	or "lambda". Extension openers open links of a certain extension, pattern
	openers match a string or regex, and lambdas open a link when a callable
	(that accepts the link as an argument) returns true.
	'''
	#storage for openers
	defaults = []
	exts = {}
	sites = {}
	lambdas = []
	lambda_lut = []

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
		#call the function normally
		if hasattr(self, "func"):
			return self.func(*args, **kw)
		#coroutinize the function unless it already is one
		#(i.e. with stacked wrappers or async def)
		func = args[0]
		if not asyncio.iscoroutinefunction(func):
			func = asyncio.coroutine(func)

		#gross if statements
		if self._type == "default":
			self.defaults.append(func)
		elif self._type == "extension":
			self.exts[self._argument] = func
		elif self._type == "pattern":
			self.sites[self._argument] = func
		elif self._type == "lambda":
			self.lambdas.append(self._argument)
			self.lambda_lut.append(func)
		#allow stacking wrappers
		return func

	@classmethod
	def get(cls, link, default):
		#don't need to step through opener types if default is set
		if default:
			return cls.defaults[default-1]
		#check from ext
		ext = get_extension(link)
		ext_opener = cls.exts.get(ext)
		if ext_opener is not None:
			return ext_opener
		#check for patterns
		for i, j in cls.sites.items():
			found = False
			#compiled regex
			if isinstance(i, re.Pattern):
				found = i.search(link)
			elif isinstance(i, str):
				found = 1+link.find(i)
			if found:
				return j
		#check for lambdas
		for i, j in zip(cls.lambdas, cls.lambda_lut):
			if i(link):
				return j
		return cls.defaults[0]

#PREDEFINED OPENERS-------------------------------------------------------------
@opener("extension", "jpeg")
@opener("extension", "jpg")
@opener("extension", "jpg:large")
@opener("extension", "png")
@opener("extension", "png:large")
async def images(main, link):
	'''Start feh (or replaced image viewer) in main.loop'''
	if not IMG_ARGS:
		return await browser(main, link)
	main.blurb.push("Displaying image...")
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
async def videos(main, link):
	'''Start mpv (or replaced video player) in main.loop'''
	if not MPV_ARGS:
		return await browser(main, link)
	main.blurb.push("Playing video...")
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
