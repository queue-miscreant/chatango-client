#!/usr/bin/env python3
#linkopen.py
'''Library for opening links. Allows extension through wrappers
Open links by file extension, site pattern, or lambda truth
evaluation.
Althought this does not import .display (or any other module in the package),
open_link expects an instance of display.main as its first argument.'''

import re
import os #for stupid stdout/err hack
from threading import Thread
import subprocess
from webbrowser import open_new_tab

#canonical link regex
LINK_RE = re.compile("(https?://.+?\\.[^`\\s]+)[`\\s]")
IMG_PATH = 'feh'
MPV_PATH = 'mpv'
_lastlinks = []

_defaults = []
_exts = {}
_sites = {}
_lambdas = []
_lambdalut = []

def getlinks():
	return _lastlinks

def reverselinks():
	'''Get links, but sans protocol and in reverse'''
	return ["%s: %s"%(len(_lastlinks)-i,j.replace("http://","").replace("https://",""))\
		 for i,j in enumerate(reversed(_lastlinks))]

def getdefaults():
	'''Get the names of the default functions. These are hopefully descriptive enough'''
	return ['default'] + [i.__name__ for i in _defaults]

def parseLinks(raw):
	'''Add links to lastlinks'''
	global _lastlinks
	newLinks = []
	#look for whole word links starting with http:// or https://
	#don't add the same link twice
	for i in LINK_RE.findall(raw+" "):
		if i not in newLinks:
			newLinks.append(i)
	_lastlinks += newLinks

def extractext(link):
	'''Ignore common post-extension formatting, e.g. .png?revision'''
	ext = link[link.rfind('.')+1:]
	lenext = len(ext)
	slash = ext.find('/')+1 
	quest = ext.find('?')+1
	#yes this looks stupid, yes it works
	trim = quest and (slash and min(slash,quest) or quest) or slash
	if trim:
		ext = ext[:trim-1]
	return ext.lower()

#---------------------------------------------------------------
def opener(func):
	'''Set a default opener'''
	global _defaults
	_defaults.append(func)

def extopener(ext):
	'''Set an extension opener for extension `ext`'''
	def wrap(func):
		global _exts
		_exts[ext] = func
		#allow stacking wrappers
		return func
	return wrap

def pattopener(pattern):
	'''Set an extension opener for website pattern `pattern`'''
	def wrap(func):
		global _sites
		_sites[pattern] = func
		return func
	return wrap

def lambdaopener(lamb):
	'''Set a lambda opener to run when `lamb` returns true'''
	def wrap(func):
		global _lambdas,_lambdalut
		link_opener.lambdas.append(lamb)
		link_opener.lambdalut.append(func)
		return func
	return wrap

#---------------------------------------------------------------
def open_link(client,link,default = 0):
	ext = extractext(link)
	if not default:
		run = _exts.get(ext)
		if run:
			return run(client,link,ext)
		else:
			for i,j in _sites.items():
				if 1+link.find(i):
					return j(client,link)
			for i,j in enumerate(_lambdas):
				if j(link):
					return _lambdalut[i](client,link)
			return _defaults[default](client,link)
	else:
		return _defaults[default-1](client,link)

#-------------------------------------------------------------------------------------------------------
#OPENERS
#start and daemonize feh (or replaced image viewing program)
@extopener("jpeg")
@extopener("jpg")
@extopener("jpg:large")
@extopener("png")
@extopener("png:large")
def images(cli,link,ext):
	cli.newBlurb("Displaying image... ({})".format(ext))
	args = [IMG_PATH, link]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except:
		cli.newBlurb("No viewer %s found"%FEH_PATH)
	
@extopener("webm")
@extopener("mp4")
@extopener("gif")
def videos(cli,link,ext):
	'''Start and daemonize mpv (or replaced video playing program)'''
	cli.newBlurb("Playing video... ({})".format(ext))
	args = [MPV_PATH, link, "--pause"]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except:
		cli.newBlurb("No player %s found"%MPV_PATH)

@opener
def browser(cli,link):
	'''Open new tab'''
	cli.newBlurb("Opened new tab")
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
