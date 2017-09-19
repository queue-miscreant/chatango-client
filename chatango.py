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
import os
import os.path as path
import asyncio
from socket import gaierror
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
#constants for chatango
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
OPTION_NAMES = \
	["Mouse:"
	,"Multiple link open warning threshold:"
	,"Save ignore list:"
	,"Console bell on reply:"
	,"256 colors:"
	,"HTML colors:"
	,"Colorize anon names:"]

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

def parsePost(post, me, ishistory):
	#and is short-circuited
	isreply = me is not None and ('@'+me.lower() in post.post.lower())
	#format as ' user: message'; the space is for the channel
	msg = " {}: {}".format(post.user,post.post)
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
		self.members.clear()
		yield from self.mainOverlay.msgSystem("Connecting")
		try:
			yield from self.joinGroup(self.creds["room"])
		except gaierror:
			self.mainOverlay.msgSystem("Failed to connect to room '%s'" %
				self.creds["room"])
	
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
		if self.options["bell"] and msg[2] and not msg[3]:
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
		self.mainOverlay.msgSystem("Flood ban warning issued")

	@asyncio.coroutine
	def onFloodBan(self, group, secs):
		self.onFloodBanRepeat(group, secs)

	@asyncio.coroutine
	def onFloodBanRepeat(self, group, secs):
		self.mainOverlay.msgSystem("You are banned for %d seconds"%secs)
	
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
			yield from self.mainOverlay.msgSystem("Connection lost; press any key to reconnect")
			client.BlockingOverlay(self.mainOverlay.parent,
				self.reconnect(),"connect").add()
		else:
			self.mainOverlay.msgSystem("Connection error occurred. Try joining another room with ^T")

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
						,"f12":		self.options
						,"^n":		self.addignore
						,"^t":		self.joingroup
						,"^g":		self.openlastlink
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
			except Exception as e: client.perror(e)
			return 
		self.text.complete()
	
	def linklist(self):
		'''List accumulated links'''
		linksList = self.lastlinks

		#enter key
		def select(me):
			if not me.list: return
			current = linksList[len(me.list)-me.it-1] #this enforces the wanted link is selected
			client.open_link(self.parent,current,me.mode)
			if current not in self.visited_links:
				self.visited_links.append(current)
				self.recolorlines()
			#exit
			return -1

		def drawVisited(string,i,maxval):
			current = self.lastlinks[maxval-i-1] #this enforces the wanted link is selected
			try:
				if current in self.visited_links:
					string.insertColor(0,self.parent.get256color(245))
			except: pass

		box = client.ListOverlay(self.parent,[i.replace("https://","").replace("http://","")
			for i in reversed(linksList)], drawVisited, client.getDefaults())
		box.addKeys({"enter":select
					,"tab": client.override(select)})
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
		def drawIgnored(string,i,maxval):
			selected = dispList[i]
			if selected.split(' ')[0] not in self.bot.ignores: return
			string[:-1]+'i'
			string.insertColor(-1,3)
		
		box = client.ListOverlay(self.parent,dispList,drawIgnored)
		box.addKeys({
			"enter":select
			,"tab":tab
		})
		box.add()

	def setformatting(self):
		'''Chatango formatting settings'''
		#select which further input to display
		def select(me):
			formatting = self.bot.creds["formatting"]
			furtherInput = None
			#ask for font color
			if me.it == 0:
				def selectSlide(me):
					formatting[0] = me.getHex()		#this is still by reference
					self.bot.setFormatting()
					return -1
					
				def enter(me):
					if me.it < 12:
						formatting[0] = me.getColor()
						self.bot.setFormatting()
						return -1
					else:
						me.openSliders(selectSlide)

				furtherInput = client.ColorOverlay(self.parent,formatting[0])
				furtherInput.addKeys({"enter":enter})
			#ask for name color
			elif me.it == 1:
				def selectSlide(me):
					formatting[1] = me.getHex()		#this is still by reference
					self.bot.setFormatting()
					return -1
					
				def enter(me):
					if me.it < 12:
						formatting[1] = me.getColor()
						self.bot.setFormatting()
						return -1
					else:
						me.openSliders(selectSlide)
			
				furtherInput = client.ColorOverlay(self.parent,formatting[1])
				furtherInput.addKeys({"enter":enter})
			#font face
			elif me.it == 2:
				def enter(me):
					formatting[2] = str(me.it)
					self.bot.setFormatting()
					return -1
				
				furtherInput = client.ListOverlay(self.parent,FONT_FACES)
				furtherInput.addKeys({"enter":enter})
				furtherInput.it = int(formatting[2])
			#ask for font size
			elif me.it == 3:
				def enter(me):
					formatting[3] = FONT_SIZES[me.it]
					self.bot.setFormatting()
					return -1
					
				furtherInput = client.ListOverlay(self.parent,list(map(str,FONT_SIZES)))
				furtherInput.addKeys({"enter":enter})
				furtherInput.it = FONT_SIZES.index(formatting[3])
			#insurance
			if furtherInput is None: raise Exception("How is this error even possible?")
			#add the overlay
			furtherInput.add()
			#set formatting, even if changes didn't occur
			
		box = client.ListOverlay(self.parent,["Font Color","Name Color","Font Face","Font Size"])
		box.addKeys({"enter":select})
		box.add()

	def setchannel(self):
		'''List channels'''
		def select(me):
			self.bot.channel = me.it
			return -1
		def ontab(me):
			self.bot.filtered_channels[me.it] = \
				not self.bot.filtered_channels[me.it]
			self.redolines()
		def drawActive(string,i,maxval):
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
		def select(me):
			global creds_entire, creds_readwrite

			if me.it == 0:		#mouse
				self.bot.options["mouse"] ^= 1
				self.parent.toggleMouse(self.bot.options["mouse"])
				pass
			elif me.it == 1:	#link opening
				def update(entry):
					try:
						self.bot.options["linkwarn"] = int(entry)
					except:	pass
				furtherInput = client.InputOverlay(self.parent, "Warning threshold "+\
					"for simultaneously opening links", update)
				furtherInput.add()
			elif me.it == 2:	#save ignores
				self.bot.options["ignoresave"] ^= 1
				if self.bot.options["ignoresave"]:
					creds_readwrite["ignores"] |= 2
				else:
					creds_readwrite["ignores"] &= ~2
					creds_entire["ignores"].clear()
			elif me.it == 3:	#bell on reply
				self.bot.options["bell"] ^= 1
			elif me.it == 4:	#256 colors
				self.bot.options["256color"] ^= 1
				self.parent.toggle256(self.bot.options["256color"])
				self.recolorlines()
			elif me.it == 5:	#html colors
				self.bot.options["htmlcolor"] ^= 1
				self.recolorlines()
			elif me.it == 6:	#colored anons
				self.bot.options["anoncolor"] ^= 1
				self.recolorlines()
			
		def drawOptions(string,i,maxval):
			if i == 0:		#mouse
				string[:-1]+(self.bot.options["mouse"] and "y" or "n")
				string.insertColor(-1,self.bot.options["mouse"] and 11 or 3)
			elif i == 1:	#link opening
				numlinks = str(self.bot.options["linkwarn"])
				startpos = -len(numlinks)
				string[:startpos]+numlinks
				string.insertColor(startpos,4)
			elif i == 2:	#save ignores
				string[:-1]+(self.bot.options["ignoresave"] and "y" or "n")
				string.insertColor(-1,self.bot.options["ignoresave"] and 11 or 3)
			elif i == 3:	#bell on reply
				string[:-1]+(self.bot.options["bell"] and "y" or "n")
				string.insertColor(-1,self.bot.options["bell"] and 11 or 3)
			elif i == 4:
				string[:-1]+(self.bot.options["256color"] and "y" or "n")
				string.insertColor(-1,self.bot.options["256color"] and 11 or 3)
			elif i == 5:
				string[:-1]+(self.bot.options["htmlcolor"] and "y" or "n")
				#prereqs
				if (self.bot.options["256color"]):
					#colorize y/n
					string.insertColor(-1,self.bot.options["htmlcolor"] and 11 or 3)
				else:
					try: #try making it grayed out
						string.insertColor(0,self.parent.get256color(245))
					except: pass
			elif i == 6:
				string[:-1]+(self.bot.options["anoncolor"] and "y" or "n")
				#prereqs
				if self.bot.options["256color"] and self.bot.options["htmlcolor"]:
					string.insertColor(-1,self.bot.options["anoncolor"] and 11 or 3)
				else:
					try:
						string.insertColor(0,self.parent.get256color(245))
					except: pass

		box = client.ListOverlay(self.parent, OPTION_NAMES, drawOptions)
		box.addKeys({
			"enter":select
			,"tab":	select
			,' ':	select
		})
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
		return any((
				#filtered channels
				self.bot.filtered_channels[post.channel]
				#ignored users
				,post.user.lower() in self.bot.ignores
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
				raise Exception()
			nameColor = self.parent.get256color(post.nColor)
			fontColor = self.parent.get256color(post.fColor)
		except Exception:
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
		client.perror("error occurred, aborting")
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

@client.onDone
def connectionError():
	global disconnected_error
	if disconnected_error:
		print("disconnected due to %s" % disconnected_error)

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

		keysList = client.ListOverlay(parent,dir(chatbot.mainOverlay))
		keysList.addKeys({
			"enter": lambda x: -1
		})
		return keysList

	@client.command("avatar",tabFile)
	def avatar(parent,*args):
		'''Upload the file as the user avatar'''
		chatbot = getClient()
		if not chatbot: return

		path = path.expanduser(' '.join(args))
		path = path.replace("\ ",' ')
		chatbot.uploadAvatar(path)

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
		raise IOError("Error reading creds! Aborting...") from exc

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
	except gaierror as exc:
		disconnected_error = exc
	except Exception:
		import traceback
		traceback.print_exc()
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
			raise IOError("Error writing creds!") from exc
