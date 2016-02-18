#!/usr/bin/env python3
#
#
#chatango.py:
#		Chat bot that extends the ConnectionManager class in chlib and
#		extensions to the client for chatango only.
#		The main source file.
#

import sys

if "--help" in sys.argv:
	print("""cube's chatango client
Usage:
	chatango [-c username password] [-g group]:	Start the chatango client. 

Options:
	-c:		Input credentials again
	-g:		Input group name again
	--help:		Display this page
	""")
	exit()
	
#try importing curses
try:
	import curses
	import client
except ImportError:
	print("ERROR WHILE IMPORTING CURSES, is this running on Windows?")
	exit()
import threading
import re
import json
import chlib

#constants for chatango
FONT_FACES = ["Arial",
			  "Comic Sans",
			  "Georgia",
			  "Handwriting",
			  "Impact",
			  "Palatino",
			  "Papyrus",
			  "Times New Roman",
			  "Typewriter",
			  ]
FONT_SIZES = [9,10,11,12,13,14]

#ignore list
#needed here so that commands can access it
ignores = []

#debugging function, as curses won't let normal prints occur
def op(*args):
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()
		
#read credentials from file
def readFromFile(filePath):
	try:
		jsonInput = open(filePath)
		jsonData = json.loads(jsonInput.read())
		jsonInput.close()
		return jsonData
	except Exception as exc:
		return {}

def sendToFile(filePath,jsonData):
	if filePath == '': return
	encoder = json.JSONEncoder(ensure_ascii=False)
	out = open(filePath,'w')
	out.write(encoder.encode(jsonData))

#format raw HTML data
def formatRaw(raw):
	if len(raw) == 0: return raw
	html = re.findall("(<[^<>]*?>)", raw)
	#REEEEEE CONTROL CHARACTERS GET OUT
	for j in str(raw):
		if ord(j) < 32:
			raw = raw.replace(j,"")
	#replace <br>s with actual line breaks
	#otherwise, remove html
	for i in html:
		raw = raw.replace(i,i == "<br/>" and "\n" or "")
	raw = decodeHtml(raw)
	#remove trailing \n's
	while len(raw) and raw[-1] == "\n":
		raw = raw[:-1]
		
	return raw

#fucking HTML
def decodeHtml(raw,encode=0):
	htmlCodes = [["&#39;","'"],
				 ["&gt;",">"],
				 ["&lt;","<"],
				 ["&quot;",'"'],
				 ["&amp;",'&']]
	if encode: htmlCodes = reversed(htmlCodes)
	for i in htmlCodes:
		if encode: raw = raw.replace(i[1],i[0])
		else: raw = raw.replace(i[0],i[1])
	#decode nbsps
	if not encode:
		raw = raw.replace("&nbsp;"," ")
	
	return raw

#bot for interacting with chat
class mainBot(chlib.ConnectionManager):

	parent = None
	members = []

	def __init__(self, wrapper,creds):
		chlib.ConnectionManager.__init__(self, creds['user'], creds['passwd'], False)
		
		self.parent = wrapper
		self.parent.chatBot = self
		self.creds = creds
		self.channel = 0
		
		self.addGroup(creds['room'])
		
	def setFormatting(self, group = None):
		if not group:
			 group = self.joinedGroup
		
		if self.creds.get('formatting') is None:
			self.creds['formatting'] = {'fc': "DD9211",
			'nc': "232323",
			'ff': "0",
			'fz': 12,
			}
		
		group.setFontColor(self.creds['formatting']['fc'])
		group.setNameColor(self.creds['formatting']['nc'])
		group.setFontFace(self.creds['formatting']['ff'])
		group.setFontSize(self.creds['formatting']['fz'])
		
		sendToFile('creds',self.creds)
	
	def start(self,*args):
		self.parent.newMessage('Connecting')
		self.parent.inputwin.statrefresh(self.creds.get('user'))
	
	def tryPost(self,text):
		try:
			group = getattr(self,'joinedGroup')
			group.sendPost(decodeHtml(text,1),self.channel)
		except AttributeError:
			return
	
	def recvinited(self, group):
		self.parent.newMessage("Connected to "+group.name)
		self.joinedGroup = group
		self.setFormatting(group)
		#I modified the library to pull history messages, and put them in the group's message array
		#this organizes them by time and pushes the message
		past = group.pArray.values()
		past = sorted(past,key=lambda x: x.time)
		for i in past:
			self.recvPost(group, i.user, i, 1)
		
		self.parent.printTime("Last message at ",float(past[-1].time))
		self.parent.printTime()

	def recvRemove(self,group):
		raise KeyboardInterrupt

	#on disconnect
	def stop(self):
		chlib.ConnectionManager.stop(self)
		self.parent.stop()
		
	#on message
	def recvPost(self, group, user, post, history = 0):
		#post.ip contains channel info
		if user in ignores: return

		if user not in self.members:
			self.members.append(user)
		me = self.creds.get('user')
		#and is short-circuited
		reply = me is not None and ("@"+me.lower() in post.raw.lower())
		self.parent.newPost(user, formatRaw(post.raw), reply, history, post.channel)

	def recvshow_fw(self, group):
		self.parent.newMessage("Flood ban warning issued")

	def recvshow_tb(self, group, mins, secs):
		self.recvtb(group, mins, secs)

	def recvtb(self, group, mins, secs):
		self.parent.newMessage("You are banned for %d seconds"%(60*mins+secs))
	
	#pull members when any of these are invoked
	def recvparticipant(self, group, bit, user, uid):
		self.members = group.users
		self.parent.inputwin.statrefresh(self.creds.get('user'),int(group.unum,16))
		if user == "none": user = "anon"
		bit = (bit == "1" and 1) or -1
		#notifications
		self.parent.printBlurb("%s has %s" % (user,bit+1 and "joined" or "left"))
	
	def recvg_participants(self,group):
		self.members = group.users
		self.parent.inputwin.statrefresh(self.creds.get('user'),int(group.unum,16))
		
@client.onkey("tab")
def ontab(self):
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
			self.text += client.findName(afterReply,self.chatBot.members) + " "
		self.inputwin.inrefresh(self.text)

@client.onkey(curses.KEY_F3)	
def F3(self):
	self.chat.debounce = True
	#special wrapper to manipulate inject functionality for newlines in the list
	def newLine(self):
		def ret():
			current = self.outList[self.it]
			current = current.split(' ')[0]
			if current[0] in "!#":
				current = current[1:]
			#reply
			return "@%s " % current
		return ret
	
	dispList = {i:self.chatBot.members.count(i) for i in self.chatBot.members}
	dispList = [str(i)+(j-1 and " (%d)"%j or "") for i,j in dispList.items()]
	box = client.listInput(self.screen, sorted(dispList))
	setattr(box,'onenter',newLine(box))
	setattr(box,'onKEY_RESIZE',client.resize(box,self))
	#direct input away from normal input
	loop = box.loop()
	if loop != -1:
		self.text += loop
	
	curses.curs_set(1)
	self.chat.debounce = False
	self.chat.redraw()
	self.inputwin.inrefresh(self.text)

@client.onkey(curses.KEY_F4)
def F4(self):
	self.chat.debounce = True
	
	#select which further input to display
	def select(self, replace):
		def ret():
			display = self.display
			formatting = replace.chatBot.creds['formatting']
			#ask for font color
			if self.it == 0:
				def enter(self):
					def ret():
						return client.toHexColor(self.color)
					return ret
			
				furtherInput = client.colorInput(self.screen,client.fromHexColor(formatting['fc']))
				setattr(furtherInput,'onenter',enter(furtherInput))
				setattr(furtherInput,'onKEY_RESIZE',client.resize(furtherInput,replace))
			
				loop = furtherInput.loop()
				if loop != -1:
					formatting['fc'] = loop
			#ask for name color
			elif self.it == 1:
				def enter(self):
					def ret():
						return client.toHexColor(self.color)
					return ret
			
				furtherInput = client.colorInput(self.screen,client.fromHexColor(formatting['nc']))
				setattr(furtherInput,'onenter',enter(furtherInput))
				setattr(furtherInput,'onKEY_RESIZE',client.resize(furtherInput,replace))
			
				loop = furtherInput.loop()
				if loop != -1:
					formatting['nc'] = loop
			#ask for font face
			elif self.it == 2:
				def enter(self):
					def ret():
						return self.it
					return ret
				
				furtherInput = client.listInput(self.screen,FONT_FACES)
				furtherInput.it = int(formatting['ff'])
				setattr(furtherInput,'onenter',enter(furtherInput))
				setattr(furtherInput,'onKEY_RESIZE',client.resize(furtherInput,replace))
			
				loop = furtherInput.loop()
				if loop + 1:
					formatting['ff'] = str(loop)
			#ask for font size
			elif self.it == 3:
				def enter(self):
					def ret():
						return FONT_SIZES[self.it]
					return ret
					
				furtherInput = client.listInput(self.screen,[i for i in map(str,FONT_SIZES)])
				furtherInput.it = FONT_SIZES.index(formatting['fz'])
				setattr(furtherInput,'onenter',enter(furtherInput))
				setattr(furtherInput,'onKEY_RESIZE',client.resize(furtherInput,replace))
			
				loop = furtherInput.loop()
				if loop + 1:
					formatting['fz'] = loop
			#resize just in case any resize events occurred in sub-windows
			self.onKEY_RESIZE()
			#set formatting, even if changes didn't occur
			replace.chatBot.setFormatting()
		return ret
		
	box = client.listInput(self.screen,["Font Color", "Name Color", "Font Face", "Font Size"])
	setattr(box,'onenter',select(box,self))
	setattr(box,'onKEY_RESIZE',client.resize(box,self))
	
	box.loop()
	curses.curs_set(1)
	
	self.chat.debounce = False
	self.chat.redraw()

@client.onkey(curses.KEY_F5)
def F5(self):
	self.chat.debounce = True
	def select(self,replace):
		def ret():
			replace.chatBot.channel = self.it
			return -1
		return ret
		
	box = client.listInput(self.screen,["None", "Red", "Blue", "Both"])
	setattr(box,'onenter',select(box,self))
	setattr(box,'onKEY_RESIZE',client.resize(box,self))
	box.it = self.chatBot.channel
	
	box.loop()
	curses.curs_set(1)
	self.chat.debounce = False
	self.chat.redraw()

#DEBUG ONLY
@client.onkey(curses.KEY_F12)
def F12(self):
	op(self.chat.lines)

@client.onkey(curses.KEY_MOUSE)
def mouse(self):
	try:
		_, x, y, z, state = curses.getmouse()
		lineno = self.chat.nums-y
		#if not a release, or it's not in the chat window, return
		if state > curses.BUTTON1_PRESSED: return
		if lineno < 0: return
		
		lines = self.chat.lines
		length = len(lines)
		pulled = 0
		mlines = []
		#read in reverse for links that appear, only the ones on screen
		for i in reversed(range(max(length-self.chat.nums-1,0),length)):
			#recalculate height of each message
			mlines = client.splitMessage(lines[i][0],self.chat.width)
			pulled += len(mlines)
			if pulled >= lineno:
				break
		#get the exact line from the message
		try:
			line = mlines[pulled-lineno]
		except: return
		#line noise for "make a dictionary with keys as distance from x-positon and values as regex capture"
		matches = {abs((i.start()+i.end())/2 - x):i.groups()[0] for i in re.finditer(r"<LINK (\d+?)>",line)}
		if matches == {}: return
		#get the closest capture
		ret = matches[min(matches.keys())]
		
		#they begin with an index of 0, but appear beginning with 1 (i.e LINK 1 is lastlinks[0])
		self.openLink(self.lastlinks[int(ret)-1])
	except Exception as exc:
		op(exc)

@client.onkey(curses.KEY_RESIZE)
def resize(self):
	y, x = self.screen.getmaxyx()
	old = self.chat.lines
	del self.chat
	self.chat = client.chat(y-3, x, old)
	self.inputwin = client.chatinput(y-3, x, self.inputwin.count)
	self.chat.redraw()
	self.inputwin.statrefresh(self.chatBot.creds.get('user'))
	self.inputwin.blurbrefresh()

#methods like this can be used in the form /[commandname]
@client.command('ignore')
def ignore(arglist):
	global ignores
	person = arglist[0]
	if '@' not in person: return
	person = person[1:]
	if person in ignores: return
	ignores.append(person)

@client.colorer
def channel(base,coldic,default,*args):
	coldic[1] = curses.color_pair(args[0]*2 + 8)

@client.colorer
def greentext(base,coldic,default,*args):
	lines = base.split("\n")
	tracker = 0
	for no,line in enumerate(lines):
		begin = re.match("^ \w+?: ",line) and line.find(":")+1
		if begin: coldic[begin] = default				
		if line[begin or 0:].startswith(begin and " >" or ">"):
			coldic[tracker+len(line)] = curses.color_pair(7)
		else:
			coldic[tracker+len(line)] = default
		tracker += len(line)
	
def begin(stdscr,creds):
	#this is perfect. don't fuck it up, or else stuff will stop drawing colors properly
	curses.init_pair(1,curses.COLOR_RED,	curses.COLOR_WHITE)	# red on white for system
	curses.init_pair(2,curses.COLOR_BLUE,	curses.COLOR_BLACK)	# blue on black
	curses.init_pair(3,curses.COLOR_CYAN,	curses.COLOR_BLACK)	# cyan on black
	curses.init_pair(4,curses.COLOR_MAGENTA,curses.COLOR_BLACK)	# magenta on black
	curses.init_pair(5,curses.COLOR_RED,	curses.COLOR_BLACK)	# red on black
	curses.init_pair(6,curses.COLOR_YELLOW,	curses.COLOR_BLACK)	# yellow on black
	curses.init_pair(7,curses.COLOR_GREEN,	curses.COLOR_BLACK)	# green on black (greentext only)
	curses.init_pair(8,curses.COLOR_WHITE,	curses.COLOR_BLACK)	# white on black
	curses.init_pair(10,curses.COLOR_BLACK, curses.COLOR_RED) #red
	curses.init_pair(11,curses.COLOR_BLACK, curses.COLOR_GREEN) #green
	curses.init_pair(12,curses.COLOR_BLACK, curses.COLOR_BLUE) #blue
	curses.init_pair(14,curses.COLOR_BLACK, curses.COLOR_MAGENTA) #both
	
	curses.mousemask(1)
	
	cl = client.client(stdscr)
	chat = mainBot(cl,creds)
	
	#daemonize functions
	bot_thread = threading.Thread(target=chat.main)
	bot_thread.daemon = True
	printtime = threading.Thread(target=cl.timeloop)
	printtime.daemon = True
	#start threads
	bot_thread.start()
	printtime.start()
	
	while bot_thread.is_alive():
		if cl.input():
			break

if __name__ == '__main__':
	creds = readFromFile('creds')

	formatting = creds.get('formatting')
	formatting = formatting == {} and None or formatting

	#0th arg is the program, -c is at minimum the first arg, followed by the second and third args username and password
	if len(sys.argv) >= 4 and '-c' in sys.argv:
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
	
	if not all((creds.get('user'),creds.get('passwd'),creds.get('room'))):
		creds['user'] = input("Enter your username: ")
		creds['passwd'] = input("Enter your password: ")
		creds['room'] = input("Enter the group name: ")
		
	try:
		curses.wrapper(begin,creds)
	except client.SizeException:
		print("TERMINAL SIZE TOO SMALL")
	except client.DisconnectException:
		print("DISCONNECTED")
	except KeyboardInterrupt:
		pass
