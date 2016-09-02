#!/usr/bin/env python3
#chatango.py:
'''
cube's chatango client
Usage:
	chatango [options]:	Start the chatango client. 

Options:
	-c uname pwd:	Input credentials
	-g groupname:	Input group name
	-r:				Relog
	-nc:			No custom script import
	--help:			Display this page
'''
#TODO		Something with checking premature group removes

import sys
import client
#readablity
from client import display
from client import linkopen
import chlib
import re
import json
import os

chatbot = None
write_to_save = 1
SAVE_PATH = os.path.expanduser('~/.chatango_creds')
XML_TAGS_RE = re.compile("(<[^<>]*?>)")
THUMBNAIL_FIX_RE = re.compile(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)")
#constants for chatango
FONT_FACES=	["Arial"
			,"Comic Sans"
			,"Georgia"
			,"Handwriting"
			,"Impact"
			,"Palatino"
			,"Papyrus"
			,"Times New Roman"
			,"Typewriter"
		  ]
FONT_SIZES = [9,10,11,12,13,14]
HTML_CODES = [
	["&#39;","'"],
	["&gt;",">"],
	["&lt;","<"],
	["&quot;",'"'],
	["&apos;","'"],
	["&amp;",'&'],
]

#ignore list
#needed here so that commands can access it
ignores = []
filtered_channels = [0, #white
			0, #red
			0, #blue
			0] #both

#read credentials from file
def readFromFile(filePath = SAVE_PATH):
	try:
		jsonInput = open(filePath)
		jsonData = json.loads(jsonInput.read())
		jsonInput.close()
		return jsonData
	except Exception as exc:
		return {} 
def sendToFile(jsonData,filePath = SAVE_PATH):
	if filePath == '': return
	if not write_to_save: return
	encoder = json.JSONEncoder(ensure_ascii=False)
	out = open(filePath,'w')
	out.write(encoder.encode(jsonData)) 
#the normal chatango library just takes out HTML without formatting it
#so I'm adding <br> to \n. This further gets converted by the client into multiple lines
def formatRaw(raw):
	if len(raw) == 0: return raw
	#replace <br>s with actual line breaks
	#otherwise, remove html
	for i in XML_TAGS_RE.findall(raw):
		raw = raw.replace(i,i == "<br/>" and "\n" or "")
	for i in HTML_CODES:
		raw = raw.replace(i[0],i[1])
	#remove trailing \n's
	while len(raw) and raw[-1] == "\n":
		raw = raw[:-1]
	#thumbnail fix in chatango
	raw = THUMBNAIL_FIX_RE.subn(r"\1l\2",raw)[0]

	return raw.replace("&nbsp;"," ")

#bot for interacting with chat
class chat_bot(chlib.ConnectionManager):
	members = []

	def __init__(self,creds,parent):
		self.creds = creds
		self.channel = 0
		self.isinited = 0
		self.mainOverlay = chatangoOverlay(parent,self)
		self.mainOverlay.add()
		
	def main(self):
		for num,i in enumerate(['user','passwd','room']):
			#skip if supplied
			if self.creds.get(i):
				continue
			inp = display.inputOverlay(self.mainOverlay.parent,"Enter your " + i, num == 1,True)
			inp.add()
			self.creds[i] = inp.waitForInput()
			if not display.active: return

		#wait until now to initialize the object, since now the information is guaranteed to exist
		chlib.ConnectionManager.__init__(self, self.creds['user'], self.creds['passwd'], False)
		self.isinited = 1

		chlib.ConnectionManager.main(self)

	def start(self,*args):
		self.mainOverlay.msgSystem('Connecting')
		self.mainOverlay.parent.updateinfo(None,self.creds.get('user'))
		self.addGroup(self.creds.get('room'))
	
	def stop(self):
		if not self.isinited: return
		chlib.ConnectionManager.stop(self)
	
	def reconnect(self):
		if not self.isinited: return
		self.removeGroup(self.creds.get('room'))
		self.start()
	
	def changeGroup(self,newgroup):
		self.stop()
		self.creds['room'] = newgroup
		self.addGroup(newgroup)

	def setFormatting(self, newFormat = None):
		group = self.joinedGroup
		
		if newFormat is not None:
			self.creds['formatting'] = newFormat
		
		if self.creds.get('formatting') is None:
			self.creds['formatting'] = {
			'fc': "DD9211"
			,'nc': "232323"
			,'ff': "0"
			,'fz': 12}
		group.setFontColor(self.creds['formatting']['fc'])
		group.setNameColor(self.creds['formatting']['nc'])
		group.setFontFace(self.creds['formatting']['ff'])
		group.setFontSize(self.creds['formatting']['fz'])
		
		sendToFile(self.creds)
	
	def tryPost(self,text):
		try:
			group = getattr(self,'joinedGroup')
			#replace HTML equivalents
			for i in reversed(HTML_CODES):
				text = text.replace(i[1],i[0])
			group.sendPost(text.replace("\n","<br/>"),self.channel)
		except Exception as exc:
			display.dbmsg(exc)
	
	def recvinited(self, group):
		self.mainOverlay.msgSystem("Connected to "+group.name)
		self.joinedGroup = group
		self.setFormatting()
		#I modified the library to pull history messages, and put them in the group's message array
		#this organizes them by time and pushes the message
		past = group.pArray.values()
		past = sorted(past,key=lambda x: x.time)
		for i in past:
			self.recvPost(group, i.user, i, 1)
		
		self.mainOverlay.msgTime(float(past[-1].time),"Last message at ")
		self.mainOverlay.msgTime()

	#on disconnect
	def recvRemove(self,group):
		#self.parent.unget()
		self.stop()
		
	#on message
	def recvPost(self, group, user, post, ishistory = 0):
		if user not in self.members:
			self.members.append(user)
		me = group.user
		if me[0] in '!#': me = me[1:]
		#and is short-circuited
		isreply = me is not None and ("@"+me.lower() in post.raw.lower())
		#sound bell
		if isreply and not ishistory: display.soundBell()
		#format as ' user: message'
		msg = '%s: %s'%(user,formatRaw(post.raw))
		linkopen.parseLinks(msg)
		self.mainOverlay.msgPost(msg, post.user, isreply, ishistory, post.channel)
		#extra arguments. use in colorizers

	def recvshow_fw(self, group):
		self.mainOverlay.msgSystem("Flood ban warning issued")

	def recvshow_tb(self, group, mins, secs):
		self.recvtb(group, mins, secs)

	def recvtb(self, group, mins, secs):
		self.mainOverlay.msgSystem("You are banned for %d seconds"%(60*mins+secs))
	
	#pull members when any of these are invoked
	def recvparticipant(self, group, bit, user, uid):
		self.members = group.users
		self.mainOverlay.parent.updateinfo(str(int(group.unum,16)))
		if user == "none": user = "anon"
		bit = (bit == "1" and 1) or -1
		#notifications
		self.mainOverlay.parent.newBlurb("%s has %s" % (user,bit-1 and "left" or "joined"))
	
	def recvg_participants(self,group):
		self.members = group.users
		self.mainOverlay.parent.updateinfo(str(int(group.unum,16)))

#-------------------------------------------------------------------------------------------------------
#KEYS
class chatangoOverlay(display.mainOverlay):
	def __init__(self,parent,bot):
		display.mainOverlay.__init__(self,parent)
		self.bot = bot
		self.addKeys({	'enter':	self.onenter
						,'tab':		self.ontab
						,'f2':		self.linklist
						,'f3':		self.F3
						,'f4':		self.F4
						,'f5':		self.F5
						,'btab':	self.addignore
						,'^t':		self.joingroup
						,'^g':		self.openlastlink
						,'^r':		self.reloadclient
		},1)	#these are methods, so they're defined on __init__
				
	def onenter(self):
		'''Open selected message's links or send message'''
		if self.isselecting():
			try:
				message = self.getselect()
				msg = client.decolor(message[0])+' '
				alllinks = linkopen.LINK_RE.findall(msg)
				def openall():
					for i in alllinks:
						linkopen.open_link(self.parent,i)
				if len(alllinks) > 1:
					self.parent.msgSystem('Really open %d links? (y/n)'%\
						len(alllinks))
					display.confirmOverlay(self.parent,openall).add()
				else:
					openall()
			except Exception: pass
			return 1
		text = str(self.text)
		#if it's not just spaces
		if text.count(" ") != len(text):
			#add it to the history
			self.text.clear()
			self.history.appendhist(text)
			#call the send
			self.bot.tryPost(text)

	def ontab(self):
		'''Reply to selected message or complete member name'''
		if self.isselecting():
			try:
				#allmessages contain the colored message and arguments
				message = self.getselect()
				msg = client.decolor(message[0])
				#first colon is separating the name from the message
				colon = msg.find(':')
				name = msg[1:colon]
				msg = msg[colon+2:]
				if name[0] in "!#":
					name = name[1:]
				self.text.append('@%s: `%s`'%(name,msg.replace('`','')))
			except: pass
			return 
		#only search after the last space
		lastSpace = self.text.rfind(" ")
		search = self.text[lastSpace + 1 and lastSpace:]
		#find the last @
		reply = search.rfind("@")
		if reply+1:
			afterReply = search[reply+1:]
			#look for the name starting with the text given
			if afterReply != "":
				#up until the @
				self.text.append(display.findName(afterReply,self.bot.members) + " ")

	def linklist(self):
		'''List accumulated links'''
		#enter key
		def select(me):
			if not linkopen.getlinks(): return
			current = me.list[me.it].split(":")[0] #get the number selected, not the number by iterator
			current = linkopen.getlinks()[int(current)-1] #this enforces the wanted link is selected
			linkopen.open_link(self.parent,current,me.mode)
			#exit
			return -1

		box = display.listOverlay(self.parent,linkopen.reverselinks(),None,linkopen.getdefaults())
		box.addKeys({'enter':select})
		box.add()

	def F3(self):
		'''List members of current group'''
		def select(me):
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current[0] in "!#":
				current = current[1:]
			#reply
			self.text.append("@%s " % current)
			return -1
		def tab(me):
			global ignores
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current not in ignores:
				ignores.append(current)
			else:
				ignores.remove(current)
			self.redolines()

		dispList = {i:self.bot.members.count(i) for i in self.bot.members}
		dispList = sorted([str(i)+(j-1 and " (%d)"%j or "") for i,j in dispList.items()])
		def drawIgnored(string,i):
			if dispList[i].split(' ')[0] not in ignores: return
			string.insertColor(-1,3)
			string[:-1]+'i'
		
		box = display.listOverlay(self.parent,sorted(dispList),drawIgnored)
		box.addKeys({
			'enter':select,
			'tab':tab,
		})
		box.add()

	def F4(self):
		'''Chatango formatting settings'''
		#select which further input to display
		def select(me):
			formatting = self.bot.creds['formatting']
			furtherInput = None
			#ask for font color
			if me.it == 0:
				def enter(me):
					formatting['fc'] = me.getHex()
					self.bot.setFormatting(formatting)
					return -1

				furtherInput = display.colorOverlay(self.parent,formatting['fc'])
				furtherInput.addKeys({'enter':enter})
			#ask for name color
			elif me.it == 1:
				def enter(me):
					formatting['nc'] = me.getHex()
					self.bot.setFormatting(formatting)
					return -1
			
				furtherInput = display.colorOverlay(self.parent,formatting['nc'])
				furtherInput.addKeys({'enter':enter})
			#font face
			elif me.it == 2:
				def enter(me):
					formatting['ff'] = str(me.it)
					self.bot.setFormatting(formatting)
					return -1
				
				furtherInput = display.listOverlay(self.parent,FONT_FACES)
				furtherInput.addKeys({'enter':enter})
				furtherInput.it = int(formatting['ff'])
			#ask for font size
			elif me.it == 3:
				def enter(me):
					formatting['fz'] = FONT_SIZES[me.it]
					self.bot.setFormatting(formatting)
					return -1
					
				furtherInput = display.listOverlay(self.parent,[i for i in map(str,FONT_SIZES)])
				furtherInput.addKeys({'enter':enter})
				furtherInput.it = FONT_SIZES.index(formatting['fz'])
			#insurance
			if furtherInput is None: raise Exception("How is this error even possible?")
			#add the overlay
			furtherInput.add()
			#set formatting, even if changes didn't occur
			
		box = display.listOverlay(self.parent,["Font Color","Name Color","Font Face","Font Size"])
		box.addKeys({
			'enter':select,
		})
		
		box.add()

	def F5(self):
		'''List channels'''
		def select(me):
			self.bot.channel = me.it
			return -1
		
		def ontab(me):
			global filtered_channels
			#space only
			filtered_channels[me.it] = not filtered_channels[me.it]
			self.redolines()
		
		def drawActive(string,i):
			if filtered_channels[i]: return
			col = i and i+12 or 16
			string.insertColor(-1,col)
						
		box = display.listOverlay(self.parent,["None","Red","Blue","Both"],drawActive)
		box.addKeys({
			'enter':select
			,'tab':	ontab
		})
		box.it = self.bot.channel
		
		box.add()

	def addignore(self):
		if self.isselecting():
			global ignores
			try:
				#allmessages contain the colored message and arguments
				message = self.getselect()
				msg = client.decolor(message[0])
				#first colon is separating the name from the message
				colon = msg.find(':')
				name = msg[1:colon]
				if name[0] in "!#":
					name = name[1:]
				if name in ignores: return
				ignores.append(name)
				self.redolines()
			except: pass
		return

	def reloadclient(self):
		'''Reload current group'''
		self.clearlines()
		self.bot.reconnect()

	def openlastlink(self):
		'''Open last link'''
		if not linkopen.getlinks(): return
		linkopen.open_link(self.parent,linkopen.getlinks()[-1])

	def joingroup(self):
		'''Join a new group'''
		inp = display.inputOverlay(self.parent,"Enter group name")
		inp.add()
		inp.runOnDone(lambda x: self.clearlines() or self.bot.changeGroup(x))

#COLORIZERS---------------------------------------------------------------------
#initialize colors
ordering =	('blue'
			,'cyan'
			,'magenta'
			,'red'
			,'yellow'
			)
for i in range(10):
	client.defColor(ordering[i%5],i//5) #0-10: user text
client.defColor('green',True)
client.defColor('green')		#11: >meme arrow
client.defColor('none',False,'none')	#12-15: channels
client.defColor('red',False,'red')
client.defColor('blue',False,'blue')
client.defColor('magenta',False,'magenta')
client.defColor('white',False,'white')	#16: extra drawing

#color by user's name
def getColor(name,init = 6,split = 109,rot = 6):
	if name[0] in '#!': name = name[1:]
	total = init
	for i in name:
		n = ord(i)
		total ^= (n > split) and n or ~n
	return (total+rot)%11

@display.colorize
def defaultcolor(msg,*args):
	msg.default = getColor(args[0])

#color lines starting with '>' as green; ignore replies and ' user:'
LINE_RE = re.compile(r'^([!#]?\w+?: )?(@\w* )*(.+)$',re.MULTILINE)
@display.colorize
def greentext(msg,*args):
	#match group 3 (the message sans leading replies)
	msg.colorByRegex(LINE_RE,lambda x: x[0] == '>' and 11 or None,3,'')

#color links white
@display.colorize
def link(msg,*args):
	msg.colorByRegex(linkopen.LINK_RE,display.rawNum(0),1)

#color replies by the color of the replier
REPLY_RE = re.compile(r"@\w+?\b")
@display.colorize
def names(msg,*args):
	def check(group):
		name = group[1:].lower()	#sans the @
		if name in chatbot.members:
			return getColor(name)
		return ''
	msg.colorByRegex(REPLY_RE,check)

#underline quotes
QUOTE_RE = re.compile(r"`[^`]+`")
@display.colorize
def quotes(msg,*args):
	msg.effectByRegex(QUOTE_RE,'underline')
		
#draw replies, history, and channel
@display.colorize
def chatcolors(msg,*args):
	args[1] and msg.addGlobalEffect('reverse')	#reply
	args[2] and msg.addGlobalEffect('underline')	#history
	msg.insertColor(0)		#make sure we color the name right
	(' ' + msg).insertColor(0,args[3]+12)	#channel

#COMMANDS-----------------------------------------------------------------------------------------------
@display.command('ignore')
def ignore(parent,arglist):
	global ignores
	person = arglist[0]
	if '@' == person[0]: person = person[1:]
	if person in ignores: return
	ignores.append(person)
	parent.over.redolines()

@display.command('unignore')
def unignore(parent,arglist):
	global ignores
	person = arglist[0]
	if '@' == person[0]: person = person[1:]
	if person not in ignores: return
	ignores.pop(ignores.index(person))
	parent.over.redolines()

@display.command('keys')
def listkeys(parent,args):
	'''Get list of mainOverlay'''
	keysList = display.listOverlay(parent,[])
	keysList.addKeys({
		'enter': lambda x: -1
	})
	return keysList

#-------------------------------------------------------------------------------------------------------
#FILTERS

#filter filtered channels
@display.filter
def channelfilter(*args):
	try:
		return filtered_channels[args[3]]
	except:
		return True

@display.filter
def ignorefilter(*args):
	try:
		return args[0] in ignores
	except:
		return True
#-------------------------------------------------------------------------------------------------------

def runClient(main,creds):
	#initialize chat bot
	global chatbot
	chatbot = chat_bot(creds,main)
	#main.setbot(chatbot)
	return chatbot.main

if __name__ == '__main__':
	if "--help" in sys.argv:
		print(__doc__)
		sys.exit()
	
	creds = {}
	if '-r' not in sys.argv:
		creds = readFromFile()
	else:
		write_to_save = False

	formatting = creds.get('formatting')
	formatting = formatting == {} and None or formatting

	#0th arg is the program, -c is at minimum the first arg, followed by the second and third args username and password
	if len(sys.argv) >= 4 and '-c' in sys.argv:
		write_to_save = False
		try:
			credpos = sys.argv.index('-c')
			creds['user'] = sys.argv[credpos+1]
			creds['passwd'] = sys.argv[credpos+2]
			if '-' in creds['user'] or '-' in creds['passwd']: raise Exception()
		except:
			raise Exception("Improper argument formatting")
	#same deal for group
	if len(sys.argv) >= 3 and '-g' in sys.argv:
		try:
			grouppos = sys.argv.index('-g')
			creds['room'] = sys.argv[grouppos+1]
			if '-' in creds['room']: raise Exception()
		except:
			raise Exception("Improper argument formatting")

	if '-nc' not in sys.argv:
		try:
			import custom #custom plugins
		except ImportError as exc: pass
	#start
	try:
		client.start(runClient,creds)
	finally:
		chatbot.stop()
