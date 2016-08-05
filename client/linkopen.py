#!/usr/bin/env python3
#
#linkopen.py: 	Library for opening links. Allows extension through wrappers
#		Open links by file extension, site pattern, or lambda truth
#		evaluation.
#		Althought this does not import client, it is expected to be used
#		in conjunction (move to separate directory?)
#		TODO:		Current implementation of "forcing" things to use the normal one
#				doesn't allow for opening things in a non-default way
#				consider a new framework
from threading import Thread
import subprocess
import re
import os #for stupid stdout/err hack
from webbrowser import open_new_tab

LINK_RE = re.compile("(https?://.+?\\.[^\n` 　]+)[\n` 　]")
IMG_PATH = 'feh'
MPV_PATH = 'mpv'
lastlinks = []

def reverselinks():
	#link number: link sans protocol, but in reverse
	return ["%s: %s"%(len(lastlinks)-i,j.replace("http://","").replace("https://",""))\
		 for i,j in enumerate(reversed(lastlinks))]

#add links to a list
def parseLinks(raw):
	global lastlinks
	newLinks = []
	#look for whole word links starting with http:// or https://
	#don't add the same link twice
	for i in LINK_RE.findall(raw+" "):
		if i not in newLinks:
			newLinks.append(i)
	lastlinks += newLinks

#look for the furthest / or ?
def extractext(link):
	ext = link[link.rfind('.')+1:]
	lenext = len(ext)
	slash = ext.find('/')+1 
	quest = ext.find('?')+1
	#yes this looks stupid, yes it works
	trim = quest and (slash and min(slash,quest) or quest) or slash
	if trim:
		ext = ext[:trim-1]
	return ext

def opener(func):
	setattr(link_opener,'default',staticmethod(func))

def extopener(ext):
	def wrap(func):
		setattr(link_opener,ext,staticmethod(func))
		return func
	return wrap

def pattopener(pattern):
	def wrap(func):
		link_opener.sites[pattern] = func
		return func
	return wrap

def lambdaopener(lamb):
	def wrap(func):
		link_opener.lambdas.append(lamb)
		link_opener.lambdalut.append(func)
		return func
	return wrap

class link_opener:
	sites = {}
	lambdas = []
	lambdalut = []
#	__init__ is like a static __call__
	def __init__(self,client,link,forcelink=False):
		ext = extractext(link)
		if forcelink:
			getattr(self, 'default')(client,link)
			return

		if hasattr(self,ext):
			getattr(self, ext)(client,link,ext)
		else:
			for i,j in self.sites.items():
				if 1+link.find(i):
					j(client,link)
					return
			for i in range(len(self.lambdas)):
				if self.lambdas[i](link):
					self.lambdalut[i](client,link)
			getattr(self, 'default')(client,link)
	#raise exception if not overridden
	def default(*args):
		raise Exception("No regular link handler defined")

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
	
#start and daemonize mpv (or replaced video playing program)
@extopener("webm")
@extopener("mp4")
@extopener("gif")
def videos(cli,link,ext):
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
def linked(cli,link):
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

