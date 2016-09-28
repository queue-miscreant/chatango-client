#!/usr/bin/env python3
#chatango.py:
'''
cube's chatango client
Usage:
	chatango [options]:	Start the chatango client. 

Options:
	-c user pass:	Input credentials
	-g groupname:	Input group name
	-r:				Relog
	-nc:			No custom script import
	--help:			Display this page
'''
#TODO		Something with checking premature group removes
#TODO		read more into how cArray works

#			create anonNames (which also contains tempnames)

#			mess about members to make it sort itself based on last message
#				this will resolve names by recency (@ab -> resolves to @abz over @abc if abz spoke more recently)

#TODO		iterate over argv

import sys
import client
#readablity
from client import overlay
from client import linkopen
import chlib
import re
import json
import os

chatbot = None
write_to_save = 1
SAVE_PATH = os.path.expanduser('~/.chatango_creds')
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
DEFAULT_FORMATTING = \
	["DD9211" #font color
	,"232323" #name color
	,"0"	  #font face
	,12]	  #font size

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

#bot for interacting with chat
class chat_bot(chlib.ConnectionManager):
	anon_names = []		#and tempnames
	user_names = []		#list of people
	members = []

	def __init__(self,creds,parent):
		self.creds = creds
		self.channel = 0
		self.isinited = 0
		self.mainOverlay = chatangoOverlay(parent,self)
		self.mainOverlay.add()
		#new tabbing for members, ignoring the # and ! induced by anons and tempnames
		client.tabber("@",self.members,lambda x: x[0] in "!#" and x[1:] or x)
		
	def main(self):
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
		self.stop()
		self.start()
	
	def changeGroup(self,newgroup):
		self.stop()
		self.creds['room'] = newgroup
		self.addGroup(newgroup)

	def setFormatting(self, newFormat = None):
		group = self.joinedGroup
		
		if newFormat is not None:
			self.creds['formatting'] = newFormat
		
		group.setFontColor(self.creds['formatting'][0])
		group.setNameColor(self.creds['formatting'][1])
		group.setFontFace(self.creds['formatting'][2])
		group.setFontSize(self.creds['formatting'][3])
		
		sendToFile(self.creds)
	
	def tryPost(self,text):
		try:
			group = getattr(self,'joinedGroup')
			group.sendPost(text,self.channel)
		except Exception as exc:
			overlay.dbmsg(exc)
	
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
		#double check for anons
		if not ishistory and user not in self.members:
			group.uArray[post.uid] = post.user
			self.members.append(post.user.lower())
		me = group.user
		if me[0] in '!#': me = me[1:]
		#and is short-circuited
		isreply = me is not None and ("@"+me.lower() in post.post.lower())
		#sound bell
		if isreply and not ishistory: overlay.soundBell()
		#format as ' user: message'
		msg = '%s: %s'%(user,post.post)
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
	def recvg_participants(self,group):
		#self.members.append(
		self.members.clear()		#preserve the current list reference for tabber
		self.members.extend(group.uArray.values())
		self.mainOverlay.parent.updateinfo(str(int(group.unum,16)))

	def recvparticipant(self, group, bit, user, uid):
		if user == "none":
			user = "anon"
		else:
#			self.members.clear()
#			self.members.extend(group.uArray.values())
			if (bit == "1"):
				self.members.append(user)
				self.user_names.append(user)

		self.mainOverlay.parent.updateinfo(str(int(group.unum,16)))
		#notifications
		self.mainOverlay.parent.newBlurb("%s has %s" % (user,(bit=="1") and "joined" or "left"))

#-------------------------------------------------------------------------------------------------------
#KEYS
class chatangoOverlay(overlay.mainOverlay):
	def __init__(self,parent,bot):
		overlay.mainOverlay.__init__(self,parent)
		self.bot = bot
		self.addKeys({	'enter':	self.onenter
						,'a-enter':	self.onaltenter
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
					overlay.confirmOverlay(self.parent,'Really open %d links? (y/n)'%\
						len(alllinks),openall).add()
				else:
					openall()
			except Exception as exc: client.dbmsg(exc)
			return
		text = str(self.text)
		#if it's not just spaces
		if text.count(" ") != len(text):
			#add it to the history
			self.text.clear()
			self.history.append(text)
			#call the send
			self.bot.tryPost(text)
	
	def onaltenter(self):
		'''Open link and don't stop selecting'''
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
					overlay.confirmOverlay(self.parent,openall).add()
				else:
					openall()
			except Exception as exc: client.dbmsg(exc)
		return 1

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
		self.text.complete()

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

		box = overlay.listOverlay(self.parent,linkopen.reverselinks(),None,linkopen.getdefaults())
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
		
		box = overlay.listOverlay(self.parent,sorted(dispList),drawIgnored)
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
					formatting[0] = me.getHex()
					self.bot.setFormatting(formatting)
					return -1

				furtherInput = overlay.colorOverlay(self.parent,formatting[0])
				furtherInput.addKeys({'enter':enter})
			#ask for name color
			elif me.it == 1:
				def enter(me):
					formatting[1] = me.getHex()
					self.bot.setFormatting(formatting)
					return -1
			
				furtherInput = overlay.colorOverlay(self.parent,formatting[1])
				furtherInput.addKeys({'enter':enter})
			#font face
			elif me.it == 2:
				def enter(me):
					formatting[2] = str(me.it)
					self.bot.setFormatting(formatting)
					return -1
				
				furtherInput = overlay.listOverlay(self.parent,FONT_FACES)
				furtherInput.addKeys({'enter':enter})
				furtherInput.it = int(formatting[2])
			#ask for font size
			elif me.it == 3:
				def enter(me):
					formatting[3] = FONT_SIZES[me.it]
					self.bot.setFormatting(formatting)
					return -1
					
				furtherInput = overlay.listOverlay(self.parent,list(map(str,FONT_SIZES)))
				furtherInput.addKeys({'enter':enter})
				furtherInput.it = FONT_SIZES.index(formatting[3])
			#insurance
			if furtherInput is None: raise Exception("How is this error even possible?")
			#add the overlay
			furtherInput.add()
			#set formatting, even if changes didn't occur
			
		box = overlay.listOverlay(self.parent,["Font Color","Name Color","Font Face","Font Size"])
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
						
		box = overlay.listOverlay(self.parent,["None","Red","Blue","Both"],drawActive)
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
		inp = overlay.inputOverlay(self.parent,"Enter group name")
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

@overlay.colorize
def defaultcolor(msg,*args):
	msg.default = getColor(args[0])

#color lines starting with '>' as green; ignore replies and ' user:'
LINE_RE = re.compile(r'^([!#]?\w+?: )?(@\w* )*(.+)$',re.MULTILINE)
@overlay.colorize
def greentext(msg,*args):
	#match group 3 (the message sans leading replies)
	msg.colorByRegex(LINE_RE,lambda x: x[0] == '>' and 11 or None,3,'')

#color links white
@overlay.colorize
def link(msg,*args):
	msg.colorByRegex(linkopen.LINK_RE,overlay.rawNum(0),1)

#color replies by the color of the replier
REPLY_RE = re.compile(r"@\w+?\b")
@overlay.colorize
def names(msg,*args):
	def check(group):
		name = group[1:].lower()	#sans the @
		if name in chatbot.members:
			return getColor(name)
		return ''
	msg.colorByRegex(REPLY_RE,check)

#underline quotes
QUOTE_RE = re.compile(r"`[^`]+`")
@overlay.colorize
def quotes(msg,*args):
	msg.effectByRegex(QUOTE_RE,'underline')
		
#draw replies, history, and channel
@overlay.colorize
def chatcolors(msg,*args):
	args[1] and msg.addGlobalEffect('reverse')	#reply
	args[2] and msg.addGlobalEffect('underline')	#history
	msg.insertColor(0)		#make sure we color the name right
	(' ' + msg).insertColor(0,args[3]+12)	#channel

#COMMANDS-----------------------------------------------------------------------------------------------
@overlay.command('ignore')
def ignore(parent,arglist):
	global chatbot,ignores
	person = arglist[0]
	if '@' == person[0]: person = person[1:]
	if person in ignores: return
	ignores.append(person)
	chatbot.mainOverlay.redolines()

@overlay.command('unignore')
def unignore(parent,arglist):
	global chatbot,ignores
	person = arglist[0]
	if '@' == person[0]: person = person[1:]
	if person not in ignores: return
	ignores.pop(ignores.index(person))
	chatbot.mainOverlay.redolines()

@overlay.command('keys')
def listkeys(parent,args):
	'''Get list of the chatbot's keys'''
	keysList = overlay.listOverlay(parent,dir(chatbot.mainOverlay))
	keysList.addKeys({
		'enter': lambda x: -1
	})
	return keysList

#-------------------------------------------------------------------------------------------------------
#FILTERS

#filter filtered channels
@overlay.filter
def channelfilter(*args):
	try:
		return filtered_channels[args[3]]
	except:
		return True

@overlay.filter
def ignorefilter(*args):
	try:
		return args[0] in ignores
	except:
		return True
#-------------------------------------------------------------------------------------------------------

def runClient(main,creds):
	#fill in credential holes
	for num,i in enumerate(['user','passwd','room']):
		#skip if supplied
		if creds.get(i):
			continue
		inp = overlay.inputOverlay(main,"Enter your " + ['username','password','room name'][num], num == 1,True)
		inp.add()
		creds[i] = inp.waitForInput()
		if not main.active: return
	#fill in formatting hole
	if creds.get('formatting') is None:
		#letting the program write into the constant would be stupid
		self.creds['formatting'] = []
		for i in DEFAULT_FORMATTING:
			self.creds['formatting'].append(i)
	elif isinstance(creds['formatting'],dict):	#backward compatible
		new = []
		for i in ['fc','nc','ff','fz']:
			new.append(creds['formatting'][i])
		creds['formatting'] = new

	global chatbot
	#initialize chat bot
	chatbot = chat_bot(creds,main)
	chatbot.main()

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
		if chatbot is not None:
			chatbot.stop()
