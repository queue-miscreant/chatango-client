#!/usr/bin/env python3
#
#
#chatango.py:
#		Chat bot that extends the ConnectionManager class in chlib and
#		adds extensions to the client for chatango only.
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
	print("ERROR WHILE IMPORTING CURSES, is this running on Windows cmd?")
	exit()
from threading import Thread
import subprocess
import re
import json
import chlib
import os
import time
from webbrowser import open_new_tab

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

IMG_PATH = "feh"
MPV_PATH = "mpv"

#ignore list
#needed here so that commands can access it
ignores = []
filtered_channels =	[0, #white
			0, #red
			0, #blue
			0] #both

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
	for j in raw:
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
	#thumbnail fix in chatango
	for i in re.finditer(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)",raw):
		cap = i.regs[0]
		raw = raw[:cap[0]] + i.group(1) + 'l' + i.group(2) + raw[cap[1]:]

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

#if given is at place 0 in the member name
#return rest of the member name or an empty string
def findName(given,memList):
	for i in memList:
		if i[0] in "!#":
			i = i[1:]
		if not i.find(given):
			return i[len(given):]
	return ""

#bot for interacting with chat
class chat_bot(chlib.ConnectionManager):
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
		if group is None:
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
		self.parent.msgSystem('Connecting')
		self.parent.inputwin.statrefresh()
	
	def tryPost(self,text):
		try:
			group = getattr(self,'joinedGroup')
			text = decodeHtml(text,1)
			group.sendPost(text.replace("\n","<br/>"),self.channel)
		except AttributeError:
			return
	
	def recvinited(self, group):
		self.parent.msgSystem("Connected to "+group.name)
		self.joinedGroup = group
		self.setFormatting(group)
		#I modified the library to pull history messages, and put them in the group's message array
		#this organizes them by time and pushes the message
		past = group.pArray.values()
		past = sorted(past,key=lambda x: x.time)
		for i in past:
			self.recvPost(group, i.user, i, 1)
		
		self.parent.msgTime(float(past[-1].time),"Last message at ")
		self.parent.msgTime(time.time())

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
		#sound bell
		if reply and not history: print('\a')
		#format as ' user: message'
		self.parent.msgPost(" {}: {}".format(post.user,formatRaw(post.raw)),
		#extra arguments. use in colorers
			reply, history, post.channel)

	def recvshow_fw(self, group):
		self.parent.msgSystem("Flood ban warning issued")

	def recvshow_tb(self, group, mins, secs):
		self.recvtb(group, mins, secs)

	def recvtb(self, group, mins, secs):
		self.parent.msgSystem("You are banned for %d seconds"%(60*mins+secs))
	
	#pull members when any of these are invoked
	def recvparticipant(self, group, bit, user, uid):
		self.members = group.users
		self.parent.inputwin.statrefresh(self.creds.get('user'),int(group.unum,16))
		if user == "none": user = "anon"
		bit = (bit == "1" and 1) or -1
		#notifications
		self.parent.newBlurb("%s has %s" % (user,bit+1 and "joined" or "left"))
	
	def recvg_participants(self,group):
		self.members = group.users
		self.parent.inputwin.statrefresh(self.creds.get('user'),int(group.unum,16))
#-------------------------------------------------------------------------------------------------------
#KEYS
	
@client.onkey("tab")
def ontab(self):
	#only search after the last space
	lastSpace = self.text().rfind(" ")
	search = self.text()[lastSpace + 1 and lastSpace:]

	#find the last @
	reply = search.rfind("@")
	if reply+1:
		afterReply = search[reply+1:]
		#look for the name starting with the text given
		if afterReply != "":
			#up until the @
			self.text.append(findName(afterReply,self.chatBot.members) + " ")

@client.onkey(curses.KEY_F3)
def F3(self):
	#special wrapper to manipulate inject functionality for newlines in the list
	def select(me):
		def ret():
			current = me.outList[me.it]
			current = current.split(' ')[0]
			if current[0] in "!#":
				current = current[1:]
			#reply
			self.text.append("@%s " % current)
		return ret
	
	dispList = {i:self.chatBot.members.count(i) for i in self.chatBot.members}
	dispList = [str(i)+(j-1 and " (%d)"%j or "") for i,j in dispList.items()]
	box = client.listInput(self.screen, sorted(dispList))
	box.addKeys({
		'enter':select(box),
		curses.KEY_RESIZE:client.resize(box,self)
	})
	
	self.chat.subWindow(box)

@client.onkey(curses.KEY_F4)
def F4(self):
	#select which further input to display
	def select(me):
		def ret():
			formatting = self.chatBot.creds['formatting']
			#ask for font color
			if me.it == 0:
				def enter(self):
					def ret():
						return client.toHexColor(self.color)
					return ret
			
				furtherInput = client.colorInput(self.screen,client.fromHexColor(formatting['fc']))
				furtherInput.addKeys({
					'enter':enter(furtherInput),
					curses.KEY_RESIZE:client.resize(furtherInput,me)
				})
			
				loop = furtherInput.loop()
				if loop != -1:
					formatting['fc'] = loop
			#ask for name color
			elif me.it == 1:
				def enter(self):
					def ret():
						return client.toHexColor(self.color)
					return ret
			
				furtherInput = client.colorInput(self.screen,client.fromHexColor(formatting['nc']))
				furtherInput.addKeys({
					'enter':enter(furtherInput),
					curses.KEY_RESIZE:client.resize(furtherInput,me)
				})
			
				loop = furtherInput.loop()
				if loop != -1:
					formatting['nc'] = loop
			#ask for font face
			elif me.it == 2:
				def enter(self):
					def ret():
						return self.it
					return ret
				
				furtherInput = client.listInput(self.screen,FONT_FACES)
				furtherInput.addKeys({
					'enter':enter(furtherInput),
					curses.KEY_RESIZE:client.resize(furtherInput,me)
				})
				furtherInput.it = int(formatting['ff'])
			
				loop = furtherInput.loop()
				if loop + 1:
					formatting['ff'] = str(loop)
			#ask for font size
			elif me.it == 3:
				def enter(self):
					def ret():
						return FONT_SIZES[self.it]
					return ret
					
				furtherInput = client.listInput(self.screen,[i for i in map(str,FONT_SIZES)])
				furtherInput.addKeys({
					'enter':enter(furtherInput),
					curses.KEY_RESIZE:client.resize(furtherInput,me)
				})
				furtherInput.it = FONT_SIZES.index(formatting['fz'])
			
				loop = furtherInput.loop()
				if loop + 1:
					formatting['fz'] = loop
			#set formatting, even if changes didn't occur
			self.chatBot.setFormatting()
		return ret
		
	box = client.listInput(self.screen,["Font Color", "Name Color", "Font Face", "Font Size"])
	box.addKeys({
		'enter':select(box),
		curses.KEY_RESIZE:client.resize(box,self)
	})
	
	self.chat.subWindow(box)

@client.onkey(curses.KEY_F5)
def F5(self):
	def select(me):
		def ret():
			self.chatBot.channel = me.it
			return -1
		return ret
	
	def oninput(me):
		def ret(chars):
			global filtered_channels
			#space only
			if chars[0] != 32: return
			filtered_channels[me.it] = not filtered_channels[me.it]
		return ret
	
	def drawActive(me,h,w):
		for i in range(4):
			if filtered_channels[i]:
				me.display.addstr(i+1,w," ",curses.color_pair(i and i+11 or 15))
					
	box = client.listInput(self.screen,["None", "Red", "Blue", "Both"],drawActive)
	box.addKeys({
		'enter':select(box),
		'input':oninput(box),
		curses.KEY_RESIZE:client.resize(box,self)
	})
	box.it = self.chatBot.channel
	
	self.chat.subWindow(box)
	self.chat.redraw()

#DEBUG ONLY
@client.onkey(curses.KEY_F12)
def F12(self):
	pass

@client.onkey(curses.KEY_MOUSE)
def mouse(self):
	#try to pull mouse event
	try:
		_, x, y, z, state = curses.getmouse()
	except: return
		
	lineno = self.chat.height-y
	#if not a release, or it's not in the chat window, return
	if state > curses.BUTTON1_PRESSED: return
	if lineno < 0: return
	
	lines = self.chat.lines
	length = len(lines)
	pulled = 0
	msg = ""
	#read in reverse for links that appear, only the ones on screen
	for i in reversed(range(max(length-self.chat.height-1,0),length)):
		#recalculate height of each message
		msg = lines[i][0]
		pulled += 1+len(msg)//(curses.COLS-client.indent)
		if pulled >= lineno:
			break
	#line noise for "make a dictionary with keys as distance from x-positon and values as regex capture"
	matches = {abs((i.start()+i.end())//2 - (x+curses.COLS*(pulled-lineno))):i.groups()[0] for i in re.finditer("(https?://.+?\\.[^ \n]+)",msg)}
	if matches == {}: return
	#get the closest capture
	ret = matches[min(matches.keys())]
	
	#they begin with an index of 0, but appear beginning with 1 (i.e LINK 1 is lastlinks[0])
	client.link_opener(self,ret)

#-------------------------------------------------------------------------------------------------------
#COLORERS

#color by user's name
@client.colorer
def defaultcolor(msg,coldic,*args):
	name = msg[1:msg.find(":")]
	total = 1
	for i in name:
		n = ord(i)
		total ^= (n > 109) and n or ~n
	coldic['default'] = curses.color_pair(((total + 2) % 5) + 5) | (total&2 and curses.A_BOLD)
#color lines starting with '>' as green; ignore replies and ' user:'
@client.colorer
def greentext(msg,coldic,*args):
	default = coldic.get('default')
	lines = msg.split("\n") #don't forget to add back in a char
	tracker = 0
	for no,line in enumerate(lines):
		try:
			#user:
			begin = re.match(r"^ \w+?: ",line).span(0)[1]
			#@user
			reply = re.match(r"^@\w+? ",line[begin:])
			if reply: begin += reply.span(0)[1]
			coldic[begin] = default
		except:
			begin = 0
		
		tracker += len(line)+1 #add in the newline
		if not len(line[begin:]): continue
		if line[begin] == ">":
			coldic[tracker-1] = curses.color_pair(10)
		else:
			coldic[tracker-1] = default
#links as white
@client.colorer
def link(msg,coldic,*args):
	default = coldic.get('default')
	for i in re.finditer("(https?://.+?\\.[^ \n]+)",msg):
		begin,end = i.span(0)[0],i.span(0)[1]
		coldic[begin] = default
		for j in coldic:
			if j in range(begin+1,end):
				coldic[j] = curses.color_pair(0)
		coldic[end] = curses.color_pair(0)
#draw replies, history, and channel
@client.colorer
def chatcolors(msg,coldic,*args):
	default = coldic.get('default')
	for i in coldic:
		if args[0]:
			#remove the bolding if it's a reply
			coldic[i] ^= coldic[i] & curses.A_BOLD and curses.A_BOLD
			coldic[i] |= curses.A_STANDOUT
		coldic[i] |= args[1] and curses.A_UNDERLINE
	coldic[1] = curses.color_pair(args[2]+11)
#-------------------------------------------------------------------------------------------------------
#OPENERS

#start and daemonize feh (or replaced image viewing program)
@client.opener("jpeg")
@client.opener("jpg")
@client.opener("png")
def images(client,link,ext):
	client.newBlurb("Displaying image... ({})".format(ext))
	args = [IMG_PATH, link]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except Exception as exc:
		raise Exception("failed to start image display")
	
#start and daemonize mpv (or replaced video playing program)
@client.opener("webm")
@client.opener("mp4")
@client.opener("gif")
def videos(client,link,ext):
	client.newBlurb("Playing video... ({})".format(ext))
	args = [MPV_PATH, link, "--pause"]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except Exception as exc:
		raise Exception("failed to start video display")

@client.opener("htmllink")
def linked(client,link):
	client.newBlurb("Opened new tab")
	#magic code to output stderr to /dev/null
	savout = os.dup(1)
	os.close(1)
	os.open(os.devnull, os.O_RDWR)
	try:
		open_new_tab(link)
	finally:
		os.dup2(savout, 1)
#-------------------------------------------------------------------------------------------------------
#COMMANDS

#methods like this can be used in the form /[commandname]
@client.command('ignore')
def ignore(arglist):
	global ignores
	person = arglist[0]
	if '@' not in person: return
	person = person[1:]
	if person in ignores: return
	ignores.append(person)
#-------------------------------------------------------------------------------------------------------
#FILTERS

#filter filtered channels
@client.chatfilter
def channelfilter(*args):
	try:
		return filtered_channels[args[2]]
	except:
		return True
#-------------------------------------------------------------------------------------------------------

def begin(stdscr,creds):
	client.colorPairs()
	#user colors
	curses.init_pair(5,curses.COLOR_BLUE,	curses.COLOR_BLACK)	# blue on black
	curses.init_pair(6,curses.COLOR_CYAN,	curses.COLOR_BLACK)	# cyan on black
	curses.init_pair(7,curses.COLOR_MAGENTA,curses.COLOR_BLACK)	# magenta on black
	curses.init_pair(8,curses.COLOR_RED,	curses.COLOR_BLACK)	# red on black
	curses.init_pair(9,curses.COLOR_YELLOW,	curses.COLOR_BLACK)	# yellow on black
	#user-defined colors
	curses.init_pair(10,curses.COLOR_GREEN,	curses.COLOR_BLACK)	# green on black (greentext only)
	curses.init_pair(11,curses.COLOR_BLACK,	curses.COLOR_BLACK)	# black on black (channel drawing)
	curses.init_pair(12,curses.COLOR_BLACK, curses.COLOR_RED) #red
	curses.init_pair(13,curses.COLOR_BLACK, curses.COLOR_BLUE) #blue
	curses.init_pair(14,curses.COLOR_BLACK, curses.COLOR_MAGENTA) #both
	curses.init_pair(15,curses.COLOR_WHITE, curses.COLOR_WHITE) #white for other
	
	curses.mousemask(1)
	
	cl = client.client(stdscr)
	chat = chat_bot(cl,creds)
	
	#daemonize functions
	bot_thread = Thread(target=chat.main)
	bot_thread.daemon = True
	printtime = Thread(target=cl.timeloop)
	printtime.daemon = True
	#start threads
	bot_thread.start()
	printtime.start()

	while chat.connected:
		if cl.input():
			break
		cl.inputwin.inrefresh(cl.text.display())
	
	cl.active = False
	chat.connected = False

try:
	import custom #custom plugins
except ImportError as exc:
	pass

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
			
	#input if missing information
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
