#!/usr/bin/env python3
#chatango.py:
'''
cube's chatango client
Usage:
	python chatango.py [options]:
	chatango [options]:

	Start the chatango client. 

Options:
	-c user pass:	Input credentials
	-g groupname:	Input group name
	-r:				Relog
	-nc:			No custom script import
	--help:			Display this page

Useful Key Bindings:
	F2:		Link accumulator
	F3:		List current group members
	F4:		Chat formatting menu
	F5:		Channels and filtering
	F12:	Options menu

	^G:		Open most recent link
	^R:		Refresh current group
	^T:		Switch to new group
'''
#TODO on finished implementation of NewMessages, iterateWith returns a 2-tuple of the coloring object and select number
#		adjust uses of iterateWith accordingly
import os
import os.path as path
import asyncio
import re
import json

import ch
import client
from functools import partial

__all__ = ["ChatBot","ChatangoOverlay","tabFile","convertTo256","getColor","getClient"]

#entire creds from file
creds_entire = {} 
#writability of keys of creds
#1 = read only, 2 = write only, 3 = both
creds_readwrite = {
	 "user":	3
	,"passwd":	3
	,"room":	3
	,"formatting":	3
	,"options":	3
	,"ignores":	1
	,"filtered_channels":	3
}
disconnected_error = None

#-------------------------------------------------------------------------------
#constants for chatango TODO maybe move into ch.py?
FONT_FACES = \
	["Arial"
	,"Comic Sans"
	,"Georgia"
	,"Handwriting"
	,"Impact"
	,"Palatino"
	,"Papyrus"
	,"Times New Roman"
	,"Typewriter" ]
FONT_SIZES = [9,10,11,12,13,14]

DEFAULT_OPTIONS = \
	{"mouse": 		False
	,"linkwarn":	2
	,"ignoresave":	False
	,"bell":		True
	,"256color":	False
	,"htmlcolor":	True
	,"anoncolor":	False}
DEFAULT_FORMATTING = \
	["DD9211"	#font color
	,"232323"	#name color
	,"0"		#font face
	,12]		#font size

LINK_RE = re.compile("(https?://.+?\\.[^`\\s]+)")

_client = None
def getClient():
	global _client
	if isinstance(_client,ChatBot):
		return _client

#fractur is broken, so change it to normal
mapRange = lambda charid,inrange,beginchar: (charid in inrange) and (charid - \
	inrange.start + beginchar)
badCharsets = [
	 (range(119964,119964+26),ord('A'))	#uppercase math
	,(range(119990,119990+26),ord('a'))	#lowercase math
	,(range(119860,119860+26),ord('A'))	#uppercase italic math
	,(range(119886,119886+26),ord('a'))	#lowercase italic math
	,(range(120172,120172+26),ord('A'))	#uppercase fractur
	,(range(120198,120198+26),ord('a'))	#lowercase fractur
	,(range(120068,120068+26),ord('A'))	#uppercase math fractur
	,(range(120094,120094+26),ord('a'))	#lowercase math fractur
]

def fracturMap(raw):
	ret = ""
	for i in raw:
		for f in badCharsets:
			mapped = mapRange(ord(i),f[0],f[1])
			if mapped:
				i = chr(mapped)
				break
		ret += i
	return ret

def parsePost(post, me, ishistory):
	#and is short-circuited
	isreply = me is not None and ('@'+me.lower() in post.post.lower())
	
	halfcooked = fracturMap(post.post)
	#remove egregiously large amounts of newlines (more than 2)
	cooked = ""
	newlineCounter = 0
	for i in halfcooked:
		if i == '\n':
			if newlineCounter < 2:
				cooked += i
			newlineCounter += 1
		else:
			newlineCounter = 0
			cooked += i
	#format as ' user: message'; the space is for the channel
	msg = " {}: {}".format(post.user,cooked)
	#extra arguments. use in colorizers
	return (msg, post, isreply, ishistory)

class ChatBot(ch.Manager):
	'''Bot for interacting with the chat'''
	members = client.PromoteSet()
	#event hookup

	def __init__(self, parent, creds):
		super(ChatBot,self).__init__(creds["user"],creds["passwd"],loop=parent.loop)

		self.creds = creds
		#default to the given user name
		self.me = creds.get("user") or None
		#list references
		self.ignores = self.creds["ignores"]
		self.filtered_channels = self.creds["filtered_channels"]
		self.options = self.creds["options"]

		self.connecting = False
		self.joinedGroup = None
		self.channel = 0

		self.mainOverlay = ChatangoOverlay(parent,self)
		self.mainOverlay.add()

		#disconnect from all groups on done
		client.onDone(self.leaveAll())

		#new tabbing for members, ignoring the # and ! induced by anons and tempnames
		client.Tokenize('@',self.members)
		self.loop.create_task(self.connect())

	@classmethod
	def addEvent(cls,eventname,func):
		ancestor = None
		try:
			ancestor = getattr(self,eventname)
		except AttributeError: pass
		#should be a partially applied function with 
		#the event ancestor (a coroutine generator)
		setattr(self,eventname,partial(func,ancestor=ancestor))
	
	@asyncio.coroutine
	def connect(self):
		if self.connecting: return
		self.connecting = True
		self.members.clear()
		yield from self.mainOverlay.msgSystem("Connecting")
		try:
			yield from self.joinGroup(self.creds["room"])
		except ConnectionError:
			self.mainOverlay.msgSystem("Failed to connect to room '%s'" %
				self.creds["room"])
		finally:
			self.connecting = False
	
	@asyncio.coroutine
	def reconnect(self):
		yield from self.leaveGroup(self.joinedGroup)
		self.mainOverlay.clear()
		yield from self.connect()
	
	@asyncio.coroutine
	def changeGroup(self,newgroup):
		yield from self.leaveGroup(self.joinedGroup)
		self.creds["room"] = newgroup
		self.mainOverlay.clear()
		yield from self.joinGroup(newgroup)

	def setFormatting(self):
		group = self.joinedGroup
		
		group.fColor = self.creds["formatting"][0]
		group.nColor = self.creds["formatting"][1]
		group.fFace = self.creds["formatting"][2]
		group.fSize = self.creds["formatting"][3]
	
	def tryPost(self,text):
		if self.joinedGroup is None: return
		self.loop.create_task(self.joinedGroup.sendPost(text,self.channel))

	def tryPM(self,user,text):
		if self.PMs is None: return
		self.PMs.sendPost(user,text)
		dummy = ch.Post((self.me,0,0,0,0,text),2)
		self.loop.create_task(self.onPrivateMessage(None,dummy,False))

	def parseLinks(self,raw,prepend = False):
		'''
		Add links to lastlinks. Prepend argument for adding links backwards,
		like with historical messages.
		'''
		newLinks = []
		#look for whole word links starting with http:// or https://
		#don't add the same link twice
		for i in LINK_RE.findall(raw+' '):
			if i not in newLinks:
				newLinks.append(i)
		if prepend:
			newLinks.reverse()
			self.mainOverlay.lastlinks = newLinks + self.mainOverlay.lastlinks
		else:
			self.mainOverlay.lastlinks.extend(newLinks)
	
	@asyncio.coroutine
	def onConnect(self, group):
		self.joinedGroup = group
		self.setFormatting()
		self.me = group.username
		if self.me[0] in "!#": self.me = self.me[1:]
		self.mainOverlay.parent.updateinfo(None,"{}@{}".format(self.me,group.name))
		#show last message time
		yield from self.mainOverlay.msgSystem("Connected to "+group.name)
		yield from self.mainOverlay.msgTime(group.last,"Last message at ")
		yield from self.mainOverlay.msgTime()

	@asyncio.coroutine
	def onPMConnect(self, group):
		yield from self.mainOverlay.msgSystem("Connected to PMs")

	@asyncio.coroutine
	def onPrivateMessage(self, group, post, historical):
		user = post.user
		msg = " {}: {}".format(post.user,post.post)
		yield from self.mainOverlay.msgPost(msg,post,True,historical)
		
	#on message
	@asyncio.coroutine
	def onMessage(self, group, post):
		'''On message. No event because you can just use ExamineMessage'''
		#double check for anons
		user = post.user
		if user[0] in '#!': user = user[1:]
		if user not in self.members:
			self.members.append(user.lower())
		self.parseLinks(post.post)
		msg = parsePost(post, self.me, False)
		#						  isreply		ishistory
		if self.options["bell"] and msg[2] and not msg[3] and \
		not self.mainOverlay.filterMessage(*(msg[1:])):
			client.soundBell()

		self.members.promote(user.lower())
		yield from self.mainOverlay.msgPost(*msg)

	@asyncio.coroutine
	def onHistoryDone(self, group, history):
		'''On retrieved history'''
		for post in history:
			user = post.user
			if user[0] in '#!': user = user[1:]
			if user not in self.members:
				self.members.append(user.lower())
			self.parseLinks(post.post, True)
			msg = parsePost(post, self.me, True)
			yield from self.mainOverlay.msgPrepend(*msg)
		self.mainOverlay.canselect = True

	@asyncio.coroutine
	def onFloodWarning(self, group):
		yield from self.mainOverlay.msgSystem("Flood ban warning issued")

	@asyncio.coroutine
	def onFloodBan(self, group, secs):
		yield from self.onFloodBanRepeat(group, secs)

	@asyncio.coroutine
	def onFloodBanRepeat(self, group, secs):
		yield from self.mainOverlay.msgSystem("You are banned for %d seconds" %
			secs)
	
	@asyncio.coroutine
	def onParticipants(self, group):
		'''On received joined members.'''
		self.members.extend(group.userlist)
		self.mainOverlay.recolorlines()

	@asyncio.coroutine
	def onUsercount(self, group):
		'''On user count changed.'''
		self.mainOverlay.parent.updateinfo(str(group.usercount))

	@asyncio.coroutine
	def onMemberJoin(self, group, user):
		if user != "anon":
			self.members.append(user)
		#notifications
		self.mainOverlay.parent.newBlurb("%s has joined" % user)

	@asyncio.coroutine
	def onMemberLeave(self, group, user):
		self.mainOverlay.parent.newBlurb("%s has left" % user)

	@asyncio.coroutine
	def onConnectionError(self, group, error):
		if isinstance(error,ConnectionResetError) or error == None:
			self.mainOverlay.messages.stopSelect()
			yield from self.mainOverlay.msgSystem("Connection lost; press ^R to reconnect")
		else:
			self.mainOverlay.msgSystem("Connection error occurred. Try joining another room with ^T")

#LISTMUXERS---------------------------------------------------------------------
class ListMuxer:
	def __init__(self):
		self._ordering = []
		self.indices = {}
		self.context = None
		self.parent = None

	def add(self,context):
		'''Add the muxer with ChatangoOverlay `parent`'''
		self.context = context
		self.parent = context.parent
		overlay = client.ListOverlay(self.parent
			,[self.indices[i]._doc for i in self._ordering]
			,self.drawing)
		selectSub = lambda me: self.indices[self._ordering[me.it]]._select()
		overlay.addKeys({
			"tab":		selectSub
			,"enter":	selectSub
			,' ':		selectSub
		})
		overlay.add()

	def drawing(self,me,string,i):
		element = self.indices[self._ordering[i]]
		element._drawer(self,element._getter(self.context),string)

	class _ListEl: #list element
		def __init__(self,parent,dataType,func):
			self.name = func.__name__
			if parent.indices.get(self.name):
				raise TypeError("Cannot implement element %s more than once"%\
					self.name)
			#bind parent names
			self.parent = parent
			self.parent.indices[self.name] = self
			self.parent._ordering.append(self.name)
			self._doc = func.__doc__
			self._type = dataType
			#default drawer
			if self._type == "color":
				self._drawer = self.colorDrawer
			elif self._type == "str":
				self._drawer = self.stringDrawer
			elif self._type == "enum":
				self._drawer = self.enumDrawer
			elif self._type == "bool":
				self._drawer = self.boolDrawer
			else:	#invalid type
				raise TypeError("input type %s not recognized"%self._type)

			self._getter = func
			self._setter = None

		def setter(self,func):
			'''Decorator to set setter'''
			self._setter = func
		def drawer(self,func):
			'''Decorator to set drawer'''
			self._drawer = func

		def _select(self):
			furtherInput = None
			if self._type == "color":
				furtherInput = client.ColorOverlay(self.parent.parent
					,lambda ret: self._setter(self.parent.context,ret) #callback
					,self._getter(self.parent.context))			#initial color
			elif self._type == "str":
				furtherInput = client.InputOverlay(self.parent.parent
					,self._doc								#input window text
					,lambda ret: self._setter(self.parent.context,ret)) #callback
			elif self._type == "enum":
				li,index = self._getter(self.parent.context)
				furtherInput = client.ListOverlay(self.parent.parent
					,li)		#enum entries
				furtherInput.it = index
				setCallback = lambda me: self._setter(self.parent.context,me.it)
				furtherInput.addKeys(
					{'tab':		setCallback
					,'enter':	setCallback
					,' ':		setCallback
				})
			elif self._type == "bool":
				self._setter(self.parent.context,
					not self._getter(self.parent.context))	#toggle
				return
			furtherInput.add()
			
		@staticmethod
		def colorDrawer(mux,value,coloring):
			'''Default color drawer'''
			coloring.insertColor(-1,mux.parent.get256color(value))
			coloring.effectRange(-1,0,0)
		@staticmethod
		def stringDrawer(mux,value,coloring):
			'''Default string drawer'''
			val = str(value)
			startpos = -len(val)
			coloring[:startpos]+val
			coloring.insertColor(startpos,4)	#yellow
		@classmethod
		def enumDrawer(cls,mux,value,coloring):
			'''Default enum drawer'''
			#dereference and run string drawer
			cls.stringDrawer(mux,value[0][value[1]],coloring)
		@staticmethod
		def boolDrawer(mux,value,coloring):
			'''Default bool drawer'''
			coloring[:-1]+(value and "y" or "n")
			coloring.insertColor(-1,value and 11 or 3)

	def listel(self,dataType):
		return partial(self._ListEl,self,dataType)

fromHex = lambda h: tuple(int(h[i*2:i*2+2],16) for i in range(3))

#formatting mux
formatting = ListMuxer()
@formatting.listel("color")
def fontcolor(context):
	"Font Color"
	return context.bot.creds["formatting"][0]
@fontcolor.setter
def _(context,value):
	context.bot.creds["formatting"][0] = client.ColorOverlay.toHex(value)

@formatting.listel("color")
def namecolor(context):
	"Name Color"
	return context.bot.creds["formatting"][1]
@namecolor.setter
def _(context,value):
	context.bot.creds["formatting"][1] = client.ColorOverlay.toHex(value)

@formatting.listel("enum")
def fontface(context):
	"Font Face"
	tab = FONT_FACES
	index = context.bot.creds["formatting"][2]
	return tab,int(index)
@fontface.setter
def _(context,value):
	context.bot.creds["formatting"][2] = str(value)

@formatting.listel("enum")
def fontsize(context):
	"Font Size"
	tab = FONT_SIZES
	index = context.bot.creds["formatting"][3]
	return list(map(str,tab)),tab.index(index)
@fontsize.setter
def _(context,value):
	context.bot.creds["formatting"][3] = FONT_SIZES[value]

options = ListMuxer()

@options.listel("bool")
def mouse(context):
	"Mouse:"
	return context.bot.options["mouse"]
@mouse.setter
def _(context,value):
	context.bot.options["mouse"] = value

@options.listel("str")
def linkwarn(context):
	"Multiple link open warning threshold:"
	return context.bot.options["linkwarn"]
@linkwarn.setter
def _(context,value):
	try:
		context.bot.options["linkwarn"] = int(value)
	except Exception as exc:
		client.perror(exc)

@options.listel("bool")
def ignoresave(context):
	"Save ignore list:"
	return context.bot.options["ignoresave"]
@ignoresave.setter
def _(context,value):
	global creds_readwrite,creds_entire
	context.bot.options["ignoresave"] = value
	if value:
		creds_readwrite["ignores"] |= 2
	else:
		creds_readwrite["ignores"] &= ~2
		creds_entire["ignores"].clear()

@options.listel("bool")
def bell(context):
	"Console bell on reply:"
	return context.bot.options["bell"]
@bell.setter
def _(context,value):
	context.bot.options["bell"] = value

@options.listel("bool")
def two56(context):
	"256 colors:"
	return context.bot.options["256color"]
@two56.setter
def _(context,value):
	context.bot.options["256color"] = value
	context.parent.toggle256(context.bot.options["256color"])
	context.recolorlines()

@options.listel("bool")
def htmlcolor(context):
	"HTML colors:"
	return context.bot.options["htmlcolor"]
@htmlcolor.setter
def _(context,value):
	context.bot.options["htmlcolor"] = value
	context.recolorlines()
@htmlcolor.drawer
def _(mux,value,coloring):
	'''Gray out if invalid due to 256 colors being off'''
	htmlcolor.boolDrawer(mux,value,coloring)
	if not mux.indices["two56"]._getter(mux.context):
		coloring.clear()
		coloring.insertColor(0,mux.parent.get256color(245))

@options.listel("bool")
def anoncolor(context):
	"Colorize anon names:"
	return context.bot.options["anoncolor"]
@anoncolor.setter
def _(context,value):
	context.bot.options["anoncolor"] = value
	context.recolorlines()
@anoncolor.drawer
def _(mux,value,coloring):
	'''Gray out if invalid due to 256 colors and HTML colors being off'''
	anoncolor.boolDrawer(mux,value,coloring)
	if not (mux.indices["two56"]._getter(mux.context) and \
	mux.indices["htmlcolor"]._getter(mux.context)):
		coloring.clear()
		coloring.insertColor(0,mux.parent.get256color(245))

#OVERLAY EXTENSION--------------------------------------------------------------
class ChatangoOverlay(client.MainOverlay):
	def __init__(self,parent,bot):
		#XXX not sure why, but lastlinks after the super raises an exception
		self.lastlinks = []
		self.visited_links = []

		super(ChatangoOverlay, self).__init__(parent)
		self.bot = bot
		self.canselect = False
		self.addKeys({	"enter":	self.onenter
						,"a-enter":	self.onaltenter
						,"tab":		self.ontab
						,"f2":		self.linklist
						,"f3":		self.listmembers
						,"f4":		self.setformatting
						,"f5":		self.setchannel
						,"f6":		self.listreplies
						,"f7":		self.pmConnect
						,"f12":		self.options
						,"^f":		self.ctrlf
						,"^g":		self.openlastlink
						,"^n":		self.addignore
						,"^t":		self.joingroup
						,"^r":		self.reloadclient
				,"mouse-left":		self.clickOnLink
				,"mouse-middle":	client.override(self.openSelectedLinks,1)
		},1)	#these are methods, so they're defined on __init__

	def _maxselect(self):
		#when we've gotten too many messages
		group = self.bot.joinedGroup
		if group:
			self.canselect = False
			group.getMore()
			#wait until we're done getting more
			self.parent.newBlurb("Fetching more messages")
		super(ChatangoOverlay,self)._maxselect()

	def clear(self):
		super(ChatangoOverlay, self).clear()
		self.lastlinks.clear()
	
	def openSelectedLinks(self):
		message = self.messages.getselected()
		try:	#don't bother if it's a system message (or one with no "post")
			msg = message[1][0].post
		except: return
		alllinks = LINK_RE.findall(msg)
		def openall():
			for i in alllinks:
				client.open_link(self.parent,i)
				if i not in self.visited_links:
					self.visited_links.append(i)
			#don't recolor if the list is empty
			#need to recolor ALL lines, not just this one
			if alllinks: self.recolorlines()
				
		if len(alllinks) >= self.bot.options["linkwarn"]:
			self.parent.holdBlurb(
				"Really open {} links? (y/n)".format(len(alllinks)))
			client.ConfirmOverlay(self.parent, openall).add()
		else:
			openall()

	def clickOnLink(self,x,y):
		msg, pos = self.messages.getMessageFromPosition(x,y)
		if pos == -1: return 1
		link = ""
		smallest = -1
		#look over all link matches; take the middle and find the smallest delta
		for i in LINK_RE.finditer(str(msg[0])):
			linkpos = (i.start() + i.end()) // 2
			distance = abs(linkpos - pos)
			if distance < smallest or smallest == -1:
				smallest = distance
				link = i.group()
		if link:
			client.open_link(self.parent,link)
			self.visited_links.append(link)
			self.recolorlines()
		return 1

	def onenter(self):
		'''Open selected message's links or send message'''
		if self.messages.getselected():
			self.openSelectedLinks()
			return
		text = str(self.text)
		firstSpace = text.find(' ')
		if firstSpace != -1 and text[:firstSpace] == "/w":
			secondSpace = text.find(' ',firstSpace+1)
			if secondSpace != -1 and text[firstSpace+1] == "@":
				user = text[firstSpace+2:secondSpace]
				self.text.clear()
				self.bot.tryPM(user,text[secondSpace+1:])
			return
			
		#if it's not just spaces
		if text.count(' ') != len(text):
			#add it to the history
			self.text.clear()
			self.history.append(text)
			#call the send
			self.bot.tryPost(text)
	
	def onaltenter(self):
		'''Open link and don't stop selecting'''
		if self.messages.getselected():
			self.openSelectedLinks()
		return 1

	def ontab(self):
		'''Reply to selected message or complete'''
		message = self.messages.getselected()
		if message:
			try:
				#allmessages contain the colored message and arguments
				msg,name = message[1][0].post, message[1][0].user
				if name[0] in "!#": name = name[1:]
				if self.bot.me:
					msg = msg.replace("@"+self.bot.me,"")
				self.text.append("@{}: `{}`".format(name, msg.replace('`',"")))
			except: pass
			return 
		self.text.complete()
	
	def linklist(self):
		'''List accumulated links'''
		linksList = self.lastlinks

		#enter key
		def select(me):
			'''Open link with selected opener'''
			if not me.list: return
			#try to get selected links
			alllinks = me.selectedList()
			if len(alllinks):
				#function to open all links, like in above selected message
				def openall():
					needRecolor = False
					for i in alllinks:
						current = me.raw[len(me.list)-i-1]
						client.open_link(self.parent,current,me.mode)
						if current not in self.visited_links:
							self.visited_links.append(current)
							needRecolor = True
					#self explanatory
					if needRecolor: self.recolorlines()

				if len(alllinks) >= self.bot.options["linkwarn"]:
					self.parent.holdBlurb(
						"Really open {} links? (y/n)".format(len(alllinks)))
					client.ConfirmOverlay(self.parent, openall).add()
				else:
					openall()
				me.clear()
				return -1

			current = me.raw[len(me.list)-me.it-1] #this enforces the wanted link is selected
			client.open_link(self.parent,current,me.mode)
			if current not in self.visited_links:
				self.visited_links.append(current)
				self.recolorlines()
			#exit
			return -1

		def drawVisited(me,string,i):
			current = me.raw[len(me.list)-i-1]
			try:
				if current in self.visited_links:
					string.insertColor(0,self.parent.get256color(245))
			except: pass

		buildList = lambda raw: [i.replace("https://","").replace("http://","")
			for i in reversed(raw)]

		box = client.VisualListOverlay(self.parent, (buildList,linksList),
			drawVisited, client.getDefaults())
		box.addKeys({"enter":	select
					,"tab": 	client.override(select)})
		box.add()

	def listmembers(self):
		'''List members of current group'''
		if self.bot.joinedGroup is None: return
		def select(me):
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current[0] in "!#":
				current = current[1:]
			#reply
			self.text.append("@%s " % current)
			return -1
		def tab(me):
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current not in self.bot.ignores:
				self.bot.ignores.append(current)
			else:
				self.bot.ignores.remove(current)
			self.redolines()

		users = self.bot.joinedGroup.userlist
		dispList = {i:users.count(i) for i in users}
		dispList = sorted([i.lower()+(j-1 and " (%d)"%j or "") \
			for i,j in dispList.items()])
		def drawIgnored(me,string,i):
			selected = me.list[i]
			if selected.split(' ')[0] not in self.bot.ignores: return
			string[:-1]+'i'
			string.insertColor(-1,3)
		
		box = client.ListOverlay(self.parent,dispList,drawIgnored)
		box.addKeys({
			"enter":	select
			,"tab":		tab
		})
		box.add()

	def setformatting(self):
		'''Chatango formatting settings'''
		formatting.add(self)

	def setchannel(self):
		'''List channels'''
		def select(me):
			self.bot.channel = me.it
			return -1
		def ontab(me):
			self.bot.filtered_channels[me.it] = \
				not self.bot.filtered_channels[me.it]
			self.redolines()
		def drawActive(me,string,i):
			if self.bot.filtered_channels[i]: return
			col = i and i+12 or 16
			string.insertColor(-1,col)
						
		box = client.ListOverlay(self.parent,["None","Red","Blue","Both"],drawActive)
		box.addKeys({
			"enter":select
			,"tab":	ontab
		})
		box.it = self.bot.channel
		box.add()

	def options(self):
		'''Options'''
		options.add(self)

	def listreplies(self):
		'''List replies in a convenient overlay'''
		try:
			lazylist = client.LazyIterList(
				self.messages.iterateWith(lambda _,isreply,__: isreply))
		except TypeError:
			self.parent.newBlurb("No replies have been accumulated")
			return

		def scroll(me,step):
			attempt = lazylist.step(step)
			if attempt:
				me.changeDisplay(attempt)
			elif step == 1:
				self.parent.newBlurb("Earliest reply selected")
			elif step == -1:
				self.parent.newBlurb("Latest reply selected")

		box = client.DisplayOverlay(self.parent,lazylist[0],"    ")
		box.addKeys({
			"a-j":	lambda me: scroll(me,-1)
			,"a-k":	lambda me: scroll(me,1)
		})
		box.add()

	def pmConnect(self):
		self.parent.loop.create_task(self.bot.joinPMs())

	def ctrlf(self):
		'''Ctrl-f style message stepping'''

		def search(string):
			try:
				lazylist = client.LazyIterList(self.messages.iterateWith(
					lambda post,_,__: -1 != post.post.find(string)))
			except TypeError:
				self.parent.newBlurb("No message containing `%s` found"%string)
				return
			
			def scroll(me,step):
				attempt = lazylist.step(step)
				if attempt:
					me.changeDisplay(attempt)
				elif step == 1:
					self.parent.newBlurb("No earlier instance of `%s`"%string)
				elif step == -1:
					self.parent.newBlurb("No later instance of `%s`"%string)

			newbox = client.DisplayOverlay(self.parent,lazylist[0],"    ")
			newbox.addKeys({
				"a-j":	lambda me: scroll(me,-1)
				,"a-k":	lambda me: scroll(me,1)
				,"n":	lambda me: scroll(me,-1)
				,"N":	lambda me: scroll(me,1)
			})
			newbox.add()

		#minimalism
		box = client.InputOverlay(self.parent,None,search)
		box.text.setnonscroll("^f: ")
		box.add()

	def addignore(self):
		'''Add ignore from selected message'''
		message = self.messages.getselected()
		if message:
			try:
				#allmessages contain the colored message and arguments
				name = message[1][0].user
				if name[0] in "!#": name = name[1:]
				if name in self.bot.ignores: return
				self.bot.ignores.append(name)
				self.redolines()
			except: pass
		return

	def reloadclient(self):
		'''Reload current group'''
		self.parent.loop.create_task(self.bot.reconnect())

	def openlastlink(self):
		'''Open last link'''
		linksList = self.lastlinks
		if not linksList: return
		last = linksList[-1]
		client.open_link(self.parent,last)
		if last not in self.visited_links:
			self.visited_links.append(last)
			self.recolorlines()

	def joingroup(self):
		'''Join a new group'''
		inp = client.InputOverlay(self.parent,"Enter group name",
			self.bot.changeGroup)
		inp.add()

	def filterMessage(self, post, isreply, ishistory):
		user = post.user
		if user[0] in ("!","#"):
			user = post.user[1:]
		return any((
				#filtered channels
				self.bot.filtered_channels[post.channel]
				#ignored users
				,user.lower() in self.bot.ignores
		))

	def colorizeMessage(self, msg, post, isreply, ishistory):
		rawWhite = client.rawNum(0)
		#these names are important
		nameColor = rawWhite
		fontColor = rawWhite
		visitedLink = rawWhite
		try:
			visitedLink = self.parent.get256color(245)
			#use name colors?
			if not self.bot.options["htmlcolor"] or \
			(self.bot.options["anoncolor"] and post.user[0] in "#!"):
				raise Exception
			nameColor = self.parent.get256color(post.nColor)
			fontColor = self.parent.get256color(post.fColor)
		except Exception as exc:
			nameColor = getColor(post.user)
			fontColor = getColor(post.user)
			
		#greentext, font color
		textColor = lambda x: x[0] == '>' and 11 or fontColor
		msg.colorByRegex(LINE_RE, textColor, group = 3)

		#links in white
		linkColor = lambda x: (x in self.visited_links) and visitedLink or rawWhite
		msg.colorByRegex(LINK_RE, linkColor, fontColor, 1)

		#underline quotes
		msg.effectByRegex(QUOTE_RE,1)

		#make sure we color the name right
		msg.insertColor(1, nameColor)
		#insurance the @s before a > are colored right
		#		space/username/:(space)
		msgStart = 1+len(post.user)+2
		if not msg.coloredAt(msgStart):
			msg.insertColor(msgStart,fontColor)
		if isreply:   msg.addGlobalEffect(0,1)
		if ishistory: msg.addGlobalEffect(1,1)
		#channel
		msg.insertColor(0,post.channel + 12)

LINE_RE = re.compile(r"^( [!#]?\w+?: (@\w* )*)?(.+)$",re.MULTILINE)
REPLY_RE = re.compile(r"@\w+?\b")
QUOTE_RE = re.compile(r"@\w+?: `[^`]+`")

#color by user's name
def getColor(name,init = 6,split = 109,rot = 6):
	if name[0] in "#!": name = name[1:]
	total = init
	for i in name:
		n = ord(i)
		total ^= (n > split) and n or ~n
	return (total+rot)%11

def tabFile(patharg):
	'''A file tabbing utility'''
	findpart = patharg.rfind(path.sep)
	#offset how much we remove
	numadded = 0
	initpath,search = patharg[:findpart+1], patharg[findpart+1:]
	try:
		if not patharg or patharg[0] not in "~/": #try to generate full path
			newpath = path.join(os.getcwd(),initpath)
			ls = os.listdir(newpath)
		else:
			ls = os.listdir(path.expanduser(initpath))
	except (NotADirectoryError, FileNotFoundError):
		client.perror("error occurred, aborting tab attempt on ", patharg)
		return [],0
		
	suggestions = []
	if search: #we need to iterate over what we were given
		#insert \ for the suggestion parser
		suggestions = sorted([' ' in i and '"%s"' % (initpath+i).replace('"',r"\"")
			or (initpath+i).replace('"',r"\"") for i in ls if not i.find(search)])
	else: #otherwise ignore hidden files
		suggestions = sorted([' ' in i and '"%s"' % (initpath+i).replace('"','\"')
			or (initpath+i).replace('"',r"\"") for i in ls if i.find('.')])

	if not suggestions:
		return [],0
	return suggestions,numadded - len(patharg)

#stuff to do on startup
@asyncio.coroutine
def startClient(loop,creds):
	global creds_entire, creds_readwrite
	#colors in this file because ChatangoOverlay depends on it directly
	#Non-256 colors
#	TODO use 'predefined' numbers
#		base = numPreceding()
#		...
#		color('string',base+15)
#	global _beginning = client.
	ordering = \
		("blue"
		,"cyan"
		,"magenta"
		,"red"
		,"yellow")
	for i in range(10):
		client.defColor(ordering[i%5],intense=i//5) #0-10: legacy
	client.defColor("green",intense=True)
	client.defColor("green")			#11:	>
	client.defColor("none")				#12:	blank channel
	client.defColor("red","red")		#13:	red channel
	client.defColor("blue","blue")		#14:	blue channel
	client.defColor("magenta","magenta")#15:	both channel
	client.defColor("white","white")	#16:	blank channel, visible

	#COMMANDS-------------------------------------------------------------------
	@client.command("ignore")
	def ignore(parent,person,*args):
		chatbot = getClient()
		if not chatbot: return

		if '@' == person[0]: person = person[1:]
		if person in chatbot.ignores: return
		chatbot.ignores.append(person)
		chatbot.mainOverlay.redolines()

	@client.command("unignore")
	def unignore(parent,person,*args):
		chatbot = getClient()
		if not chatbot: return

		if '@' == person[0]: person = person[1:]
		if person == "all" or person == "everyone":
			chatbot.ignores.clear()
			chatbot.mainOverlay.redolines()
			return
		if person not in chatbot.ignores: return
		chatbot.ignores.remove(person)
		chatbot.mainOverlay.redolines()

	@client.command("keys")
	def listkeys(parent,*args):
		'''Get list of the ChatangoOverlay's keys'''
		#keys are instanced at runtime
		chatbot = getClient()
		if not chatbot: return

		return chatbot.mainOverlay.getHelpOverlay()

	@client.command("avatar",tabFile)
	def avatar(parent,*args):
		'''Upload the file as the user avatar'''
		chatbot = getClient()
		if not chatbot: return

		location = path.expanduser(' '.join(args))
		location = location.replace("\ ",' ')

		trim = location.find("file://")
		if not trim:
			location = location[7:]
		
		success = chatbot.uploadAvatar(location)
		if success:
			parent.newBlurb("Successfully updated avatar")
		else:
			parent.newBlurb("Failed to update avatar")

	#done preparing client constants-------------------------------------------------
	main = client.Main(loop=loop)
	mainTask = main.start()
	yield from main.prepared.wait()
		
	#fill in credential holes
	for num,i in enumerate(["user","passwd","room"]):
		#skip if supplied
		if creds.get(i) is not None: continue
		inp = client.InputOverlay(main,"Enter your " + \
			 ["username","password","room name"][num], password = num == 1)
		
		inp.add()
		try:
			creds[i] = yield from inp.result
		except:
			#future cancelled
			main.stop()
			return

	#fill in formatting hole
	if creds.get("formatting") is None:
		#letting the program write into the constant would be stupid
		creds["formatting"] = []
		for i in DEFAULT_FORMATTING:
			creds["formatting"].append(i)
	elif isinstance(creds["formatting"],dict):	#backward compatible
		new = []
		for i in ["fc","nc","ff","fz"]:
			new.append(creds["formatting"][i])
		creds["formatting"] = new

	#ignores hole
	if creds.get("ignores") is None:
		creds["ignores"] = []	#initialize it
	#filtered streams
	if creds.get("filtered_channels") is None:
		creds["filtered_channels"] = [0,0,0,0]
	#options
	if creds.get("options") is None:
		creds["options"] = {}
	for i in DEFAULT_OPTIONS:
		if creds["options"].get(i) is None:
			creds["options"][i] = DEFAULT_OPTIONS[i]

	#options
	two56colors = DEFAULT_OPTIONS["256color"] #False
	if creds.get("options"):
		if creds["options"]["ignoresave"]:
			creds_readwrite["ignores"] |= 2
		if creds["options"].get("256color") == True:
			two56colors = True

	main.toggle256(two56colors)
	main.toggleMouse(creds["options"]["mouse"])

	global _client
	_client = ChatBot(main,creds)
	return mainTask,main.exited #the future to exit the loop

#SETTINGS AND CUSTOM SCRIPTS----------------------------------------------------
#custom and credential saving setup
CREDS_FILENAME = "chatango_creds"
HOME_DIR = path.expanduser('~')
CUSTOM_PATH = path.join(HOME_DIR,".cubecli")
#save
DEPRECATED_SAVE_PATH = path.join(HOME_DIR,".%s"%CREDS_FILENAME)
SAVE_PATH = path.join(CUSTOM_PATH,CREDS_FILENAME)
#init code to import everything in custom
CUSTOM_INIT = '''
#code ripped from stackoverflow questions/1057431
#ensures the `from custom import *` in chatango.py will import all python files
#in the directory

from os.path import dirname, basename, isfile
import glob
modules = glob.glob(dirname(__file__)+"/*.py")
__all__ = [basename(f)[:-3] for f in modules \
			if not f.endswith("__init__.py") and isfile(f)]
'''
IMPORT_CUSTOM = True

if __name__ == "__main__":
	#parse arguments and start client
	import sys

	newCreds = {}
	importCustom = True
	readCredsFlag = True
	credsArgFlag = 0
	groupArgFlag = 0
	
	for arg in sys.argv:
		#if it's an argument
		if arg[0] in '-':
			#stop creds parsing
			if credsArgFlag == 1:
				newCreds["user"] = ""
			if credsArgFlag in (1,2):
				newCreds["passwd"] = ""
			if groupArgFlag:
				raise Exception("Improper argument formatting: -g without argument")
			credsArgFlag = 0
			groupArgFlag = 0
			#creds inline
			if arg == "-c":
				creds_readwrite["user"] = 0		#no readwrite to user and pass
				creds_readwrite["passwd"] = 0
				credsArgFlag = 1
				continue	#next argument
			#group inline
			elif arg == "-g":
				creds_readwrite["room"] = 2		#write only to room
				groupArgFlag = 1
				continue
			#flags without arguments
			elif arg == "-r":		#relog
				creds_readwrite["user"] = 2		#only write to creds
				creds_readwrite["passwd"] = 2
				creds_readwrite["room"] = 2
			elif arg == "-nc":		#no custom
				importCustom = False
			elif arg == "--help":	#help
				print(__doc__)
				sys.exit()
		#parse -c
		if credsArgFlag:
			newCreds[ ["user","passwd"][credsArgFlag-1] ] = arg
			credsArgFlag = (credsArgFlag + 1) % 3
		#parse -g
		if groupArgFlag:
			newCreds["room"] = arg
			groupArgFlag = 0
	#anon and improper arguments
	if credsArgFlag == 1:	#null password means temporary name
		newCreds["user"] = ""
	if credsArgFlag >= 1:	#null name means anon
		newCreds["passwd"] = ""
	if groupArgFlag:
		raise Exception("Improper argument formatting: -g without argument")

	#DEPRECATED, updating to current paradigm
	if path.exists(DEPRECATED_SAVE_PATH) or not path.exists(CUSTOM_PATH):
		import shutil
		os.mkdir(CUSTOM_PATH)
		customDir = path.join(CUSTOM_PATH,"custom")
		os.mkdir(customDir)
		with open(path.join(CUSTOM_PATH,"__init__.py"),"w") as a:
			a.write(CUSTOM_INIT)
	if path.exists(DEPRECATED_SAVE_PATH):
		shutil.move(DEPRECATED_SAVE_PATH,SAVE_PATH)

	try:
		jsonInput = open(SAVE_PATH)
		jsonData = json.loads(jsonInput.read())
		jsonInput.close()
		for i,bit in creds_readwrite.items():
			if bit&1:
				newCreds[i] = jsonData.get(i)
			#read into safe credentials regardless
			creds_entire[i] = jsonData.get(i)
	except (FileNotFoundError, ValueError):
		pass
	except Exception as exc:
		raise IOError("Fatal error reading creds! Aborting...") from exc

	#finally import custom
	if IMPORT_CUSTOM:
		sys.path.append(CUSTOM_PATH)
		from custom import *

	#start
	loop = asyncio.get_event_loop()
	mainTask = None
	try:
		start = startClient(loop,newCreds)
		mainTask,endFuture = loop.run_until_complete(start)
		if endFuture:
			loop.run_until_complete(endFuture.wait())
	except Exception:
		import traceback
		print("\x1b[31mFatal error occurred\x1b[m")
		traceback.print_exc()
		traceback.print_exc(file=sys.stderr)
	finally:
		if mainTask != None and not mainTask.done():
			mainTask.cancel()
		loop.run_until_complete(loop.shutdown_asyncgens())
		#close all loop IO
		loop.close()
		#save
		try:
			jsonData = {}
			for i,bit in creds_readwrite.items():
				if bit&2 or i not in creds_entire:
					jsonData[i] = newCreds[i]
				else:	#"safe" credentials from last write
					jsonData[i] = creds_entire[i]
			encoder = json.JSONEncoder(ensure_ascii=False)
			with open(SAVE_PATH,'w') as out:
				out.write(encoder.encode(jsonData)) 
		except KeyError:
			pass
		except Exception as exc:
			raise IOError("Fatal error writing creds!") from exc
