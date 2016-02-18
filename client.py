#!/usr/bin/env python3
#
#client.py:
#	Curses-based tentatively "general purpose" client
#
#Uses curses to display chat, with individual names being summed into colors
#Replies and system messages are special colors
#Historical messages are underlined
#

import threading
import subprocess
import curses
import os
import time
import re
from webbrowser import open_new_tab
#curses likes to wait a second on escape by default. Turn that off
os.environ.setdefault('ESCDELAY', '25')

IMAGES = ["jpg","png","jpeg"]
VIDEOS = ["gif","webm","mp4"]
COLOR_NAMES = [" Red","Green"," Blue"]

#predefined keys
#if you want to define more key events, you'll want to use
#a method titled onKEY_(key)
#check the curses module for the key names
CURSES_KEYS = {	
	9:  'tab',
	10: 'enter',
	13: 'enter',
	27: 'escape',
	127:'backspace',
}
for i in dir(curses):
	if "KEY" in i:
		CURSES_KEYS[getattr(curses,i)] = i
CURSES_KEYS[curses.KEY_ENTER] = 'enter'
CURSES_KEYS[curses.KEY_BACKSPACE] = 'backspace'

IMG_PATH = "feh"
MPV_PATH = "mpv"

colorers = []
commands = {}

def op(*args):
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()

#start and daemonize feh (or replaced image viewing program)
def display(*args):
	args = [IMG_PATH] + [i for i in args] 
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = threading.Thread(target = displayProcess.communicate)

		display_thread.setDaemon(True)

		display_thread.start()
		
	except Exception as exc:
		pass
		#raise Exception('failed to run display ({})'.format(exc))
		
#start and daemonize mpv (or replaced video playing program)
def video(*args):
	args = [MPV_PATH] + [i for i in args] + ["--pause"]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = threading.Thread(target = displayProcess.communicate)
		
		display_thread.setDaemon(True)

		display_thread.start()

	except Exception as exc:
		pass
		#raise Exception('failed to run display ({})'.format(exc))

#add take out links, add them to a list
def parseLinks(raw,lastlinks):
	#in case the raw message ends with a link
	raw += " "
	newLinks = []
	#look for whole word links starting with http:// or https://
	newLinks = [i for i in re.findall("(https?://.+?\\.[^ \n]+)[\n ]",raw)]
	#don't add the same link twice
	for i in newLinks:
		while newLinks.count(i) > 1:
			newLinks.remove(i)
	
	for i,link in enumerate(newLinks):
		raw = raw.replace(link,"<LINK %d>" % (len(lastlinks)+i+1))
	#lists are passed by reference
	lastlinks += newLinks
	#remove trailing space
	return raw[:-1]

#split message into lines to add into the curses display
def splitMessage(baseMessage, width, indent = 4):
	#parts of the message
	parts = []
	w = width
	
	for split in baseMessage.split("\n"):
		#add an indent for messages after the first newlineB
		#keep splitting up the words
		wide = bytes(split,'utf-8')
		while len(wide) >= w:
			sub, split = wordWrap(split,w,wide)
			parts.append(sub)
			wide = bytes(split,'utf-8')
			w = width-indent
			
		if split.count(" ") != len(split):
			parts.append(split)
		w = width-indent
		
	return parts
#split string into parts if in the middle of a word at the width, with unicode support
#it just works, trust me
#bytestring passed so that bytes doesn't need to be calculated many times
def wordWrap(fullString, width, byteString):
	#width+1 in case the next character is a space
	#if it's the middle of the word, split it at the last space
	if b' ' in byteString[:width+1]:
		lastSpace = byteString.rfind(b" ",int(width/2),width+1)
		if lastSpace + 1:
			a,b = unicodeWrap(fullString,lastSpace)
			return a,b[1:]
	#otherwise split at the last character in the row
	return unicodeWrap(fullString,width)
#wrap function based on byte length of characters
def unicodeWrap(fullString,width):
	i,j = 0,0
	while j < width and i < len(fullString):
		j += len(bytes(fullString[i],'utf-8'))
		i += 1
	return fullString[:i], fullString[i:]

def easyWrap(fullString,width):
	ret,_ = unicodeWrap(fullString[::-1],width-1)
	#unicode wrapping
	return ret[::-1]

#sum of name; returns a number corresponding to a curses pair between 2 and 6
def getColor(name, rot = 2):
	total = 1
	for i in name:
		n = ord(i)
		total ^= (n > 109) and n or ~n
	return ((total + rot) % 5)+2

#if given is at place 0 in the member name
#return rest of the member name or an empty string
def findName(given,memList):
	for i in memList:
		if i[0] in "!#":
			i = i[1:]
		if not i.find(given):
			return i[len(given):]
	return ""

def toHexColor(rgb):
	return ''.join([hex(i)[2:].rjust(2,'0') for i in rgb])

def fromHexColor(hexStr):
	op(hexStr)
	return [int(hexStr[2*i:2*i+2],16) for i in range(3)]

class cursesInput:
	def __init__(self,screen):
		self.screen = screen
	#usually for loop control
	def onescape(self):
		return -1
		
	def input(self):
		screen = self.screen
		chars = [screen.getch()]
		#get as many chars as possible
		screen.nodelay(1)
		next = 0
		while next+1:
			next = screen.getch()
			chars.append(next)
		screen.nodelay(0)
		
		curseAction = CURSES_KEYS.get(chars[0])
		
		if curseAction and len(chars) == 2:
			if hasattr(self,"on"+curseAction):
				return getattr(self,"on"+curseAction)()
		elif hasattr(self,"oninput") and chars[0] in range(32,255):
			getattr(self,"oninput")(chars[:-1])

class listInput(cursesInput):
	#vertical list iterator, horizontal mode changer
	it = 0
	mode = 0
	
	def __init__(self, screen, outList, drawOther = None):
		cursesInput.__init__(self, screen)	
		self.outList = outList
		height, width = screen.getmaxyx()
		self.makeWindows(height, width)
		#turn the cursor off
		curses.curs_set(0)
		if drawOther:
			setattr(self,'drawOther',drawOther)
		
	def makeWindows(self, height, width):
		#drawing calls are expensive, especially when drawing the chat
		#which means that you have to live with fullscreen lists
		#height,width,y,x = (int(i) for i in [height*.5, width*.8, height*.2, width*.1])
		height,width,y,x = (int(i) for i in [height-3,width,0,0])
		if width < 7 or height < 3 : raise SizeException()
		self.display = curses.newwin(height,width,y,x)
	
	#draw method for previous method's window
	def draw(self):
		display = self.display
		#make sure the display is legitimate
		maxy,maxx = display.getmaxyx()
		maxy-=2
		maxx-=2
		#clear, make a border
		display.erase()
		display.border()
		#which portion of the list is currently displaced
		listNum = int(self.it/maxy)
		subList = self.outList[maxy*listNum:min(maxy*(listNum+1),len(self.outList))]
		#display
		for i,value in enumerate(subList):
			#add an elipsis in the middle of the string if it can't be displayed
			if len(value) > maxx:
				half = int(maxx/2)
				value = value[:half - 3] + "..." + value[-half:]
			display.addstr(i+1,1,value,(i+maxy*listNum == self.it) and curses.A_STANDOUT)
		
		if hasattr(self,'drawOther'):
			getattr(self,'drawOther')(self)
		
		display.refresh()
	
	#predefined list iteration methods
	def onKEY_UP(self):
		self.it -= 1
		if self.it == -1:
			self.it = len(self.outList)-1
			
	def onKEY_DOWN(self):
		self.it += 1
		if self.it == len(self.outList):
			self.it = 0
	
	#loop until escape
	def loop(self):
		ret = None
		while True:
			self.draw()
			ret = self.input()
			if ret is not None: break
			
		return ret

class colorInput(listInput):
	def __init__(self, screen,initcolor = [127,127,127]):
		listInput.__init__(self,screen,[])
		self.color = initcolor
		
	def draw(self):
		display = self.display
		
		display.clear()
		display.border()
		h, w = display.getmaxyx()
		part = int(w/7)
		
		buff = lambda x: int(h*x/10)
		if buff(7)+4 >= h: raise SizeException()
		seventh = lambda x: (2*x+1)*part
		starty = lambda x:buff(1)+int(buff(6)*(1 - self.color[x]/255))
		
		self.display.addstr(buff(7) + 4,seventh(1),toHexColor(self.color).rjust(6,"0"))
						
		for i in range(3):
			#gibberish for "draw a pretty rectange of the color it represents"
			for j in range(starty(i),buff(6)):
				display.addstr(j,seventh(i)," "*part,curses.color_pair(i+10))
				
			display.addstr(buff(7) + 1, seventh(i), COLOR_NAMES[i].ljust(6),
				self.mode == i and curses.A_REVERSE)
			display.addstr(buff(7) + 2,seventh(i),(" %d"%self.color[i]).ljust(6),
				self.mode == i and curses.A_REVERSE)
		
		display.refresh()
	#color manipulation: mode represents color selected
	#up/down: increment/decrement color
	#left/right: select color
	#pgup/pgdn: increment/decrement color by 10
	#home/end: set color to 255/0
	def onKEY_UP(self):
		self.color[self.mode] += 1
		if self.color[self.mode] > 255:
			self.color[self.mode] = 255
		
	def onKEY_DOWN(self):
		self.color[self.mode] -= 1
		if self.color[self.mode] < 0:
			self.color[self.mode] = 0
		
	def onKEY_PPAGE(self):
		self.color[self.mode] += 10	
		if self.color[self.mode] > 255:
			self.color[self.mode] = 255
		
	def onKEY_NPAGE(self):
		self.color[self.mode] -= 10
		if self.color[self.mode] < 0:
			self.color[self.mode] = 0
		
	def onKEY_HOME(self):
		self.color[self.mode] = 255
		
	def onKEY_END(self):
		self.color[self.mode] = 0
		
	def onKEY_RIGHT(self):
		self.mode = (self.mode + 1) % 3
		
	def onKEY_LEFT(self):
		self.mode = (self.mode - 1) % 3

class chat:
	def __init__(self, maxy, maxx, lines = []):
		self.height = maxy-1
		self.width = maxx
		self.win = curses.newwin(maxy,maxx)
		self.win.scrollok(1)
		self.win.setscrreg(0,maxy-2)
		self.win.leaveok(1)
		self.nums = 0
		self.lines = lines
		self.debounce = False
		self.redraw()
		
	def redraw(self):
		if self.debounce: return
		#clear the window
		self.win.clear()
		#draw all chat windows
		for data in self.lines:
			self.push(data, False, False)
		#refresh
		self.win.refresh()
	
	#format expected: (string, coldic)
	def push(self, newmsg, append = True, refresh = True):
		if append: self.lines.append(newmsg)
		if self.debounce: return
		newlines = splitMessage(newmsg[0],self.width)[-self.height:]
		colors = newmsg[1]
		
		self.lines = self.lines[-100:]
		calc = min(self.nums,self.height-len(newlines))
		#scroll some lines if needed
		if self.height-self.nums <= 0:
			self.win.scroll(len(newlines))
		wholetr = 0
		for i,line in enumerate(newlines):
			linetr = 0
			linecol = {}
			for j in sorted(colors.keys()):
				if wholetr+linetr < j:
					#error found
					try:
						self.win.addstr(calc+i, linetr + (i!=0)*4, line[linetr:min(j,len(line))], colors[j])
					except:
						raise SizeException()
					linetr = min(j,len(line))
					if j > len(line): break
			wholetr += len(line)
			#self.win.addnstr(calc+i, 0, line[0], self.width, line[1])
		self.win.hline(self.height, 0, '-', self.width)
		
		self.nums = min(self.height,self.nums+len(newlines))
		if refresh: self.win.refresh()

class chatinput:
	def __init__(self, height, width, count = 0):
		self.width = width
		self.count = count
		#create chat window, input window...
		win = lambda x: curses.newwin(1, width, height + x, 0)
		
		self.inputWin = win(0)			#two after chat
		self.debugWin = win(1)			#three after chat
		self.statWin = win(2)			#last line for status
		
		self.debugWin.leaveok(1)
		self.statWin.leaveok(1)
		
		self.statWin.attron(curses.A_STANDOUT)
	
	def inrefresh(self, input = None):
		if input is not None:
			self.inputWin.clear()
			split = easyWrap(input.replace("\n",r"\n").replace("\t",r"\t").replace("\r",r"\r"),self.width-1)
			self.inputWin.addnstr(0,0,split,self.width-1)
		self.inputWin.refresh()
		
	def statrefresh(self, name, count = None):		
		if count is None: count = self.count
		else: self.count = count
		
		repeat = self.width - len(name) - len(str(count)) - 1
		if repeat <= 0: raise SizeException()
		self.statWin.addstr(0,0,"{}{}{}".format(name," "*repeat,str(count)))
		self.statWin.refresh()
		self.inputWin.refresh()
	
	def blurbrefresh(self,message = ""):
		self.debugWin.clear()
		self.debugWin.addnstr(0,0,message,self.width)
		self.debugWin.refresh()
		self.inputWin.refresh()
		
class client(cursesInput):
	lastlinks = []
	history = []
	selectHistory = 0
	text = ""
	lastBlurb = 0
	
	def __init__(self,screen):
		cursesInput.__init__(self,screen)
		y,x = screen.getmaxyx()
		self.chat = chat(y-3,x)
		self.inputwin = chatinput(y-3,x)
		self.chat.redraw()
	
	#simple method to output to the chat window
	def newMessage(self, base, coldic = None):
		if coldic is None:
			coldic = {len(base): curses.color_pair(1)}
		
		self.chat.push((base,coldic))
		self.inputwin.inrefresh()
	
	def newPost(self, user, post, reply, history, channel):
		post = parseLinks(post,self.lastlinks)
		
	#color is just a sum of the name
		#or if it's a reply to the user, then it's in reverse color
		color = getColor(user)
		formatting = reply and curses.A_REVERSE
		formatting |= history and curses.A_UNDERLINE
		
		base = " {}: {}".format(user,post)
		coldic = {}
		for i in colorers:
			i(base,coldic,curses.color_pair(color)|formatting,channel)
		
		self.newMessage(base,coldic)
	
	def printTime(self, predicate="", numtime=None):
		if numtime is None: numtime = time.time()
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime))
		self.newMessage(predicate+dtime)
	
	def printBlurb(self,message = ""):
		self.lastBlurb = time.time()
		self.inputwin.blurbrefresh(message)
				
	def onbackspace(self):
		self.text = self.text[:-1]
		self.inputwin.inrefresh(self.text)
	
	def onenter(self):
		#if it's not just spaces
		text = self.text
		if text.count(" ") != len(text):
			#good thing strings are scalars
			self.text = ""
			self.inputwin.inrefresh(self.text)
			#if it's a command
			if text[0] == '/' and ' ' in text:
				try:
					command = getattr(commands,text[1:text.find(' ')])
					command(text[text.find(' ')+1:].split(' '))
				finally:
					return
			
			self.history.append(text)
			if len(self.history) > 50:
				self.history.pop(0)
			self.chatBot.tryPost(text)
	
	def oninput(self,chars):
		#allow unicode input
		new = bytes(chars).decode()
		self.text += new
		self.inputwin.inrefresh(self.text)

	def onKEY_SHOME(self):
		self.text = ""
		self.inputwin.inrefresh(self.text)

	def openLink(self,link):
		#extension
		ext = link[link.rfind(".")+1:]
		if ext.lower() in IMAGES:
			self.printBlurb("Displaying image... ({})".format(ext))
			display(link)
		elif ext.lower() in VIDEOS:
			self.printBlurb("Playing video... ({})".format(ext))
			video(link)
		else:
			self.printBlurb("Opened new tab")
			#magic code to output stderr to /dev/null
			savout = os.dup(1)
			os.close(1)
			os.open(os.devnull, os.O_RDWR)
			try:
				open_new_tab(link)
			finally:
				os.dup2(savout, 1)
	
	def onKEY_UP(self):
		if len(self.history) > 0:
			self.selectHistory -= (self.selectHistory > 0)
			self.text = self.history[self.selectHistory]
			self.inputwin.inrefresh(self.text)
		
	def onKEY_DOWN(self):
		if len(self.history) > 0:
			self.selectHistory += (self.selectHistory < len(self.history))
			#the next element or an empty string
			self.text = self.selectHistory != len(self.history) and self.history[self.selectHistory] or ""
			self.inputwin.inrefresh(self.text)
		
	def onKEY_F2(self):
		self.chat.debounce = True
		#special wrapper to inject functionality for newlines in the list
		def newLine(self,replace):
			def ret():
				if not len(replace.lastlinks): return
				current = replace.lastlinks[len(replace.lastlinks) - 1 - self.it]
				if not self.mode:
					replace.openLink(current)
				else:
					paste(current)
				#exit
				return -1
			return ret
	
		def drawMode(self):
			display = self.display
		
			maxy,maxx = display.getmaxyx()
			display.addnstr(maxy-1,1, (self.mode and "COPY") or "DISPLAY", maxx-1, curses.A_REVERSE)
		
		#take out the protocol
		dispList = [i.replace("http://","").replace("https://","") for i in reversed(self.lastlinks)]
		#link number: link, but in reverse
		dispList = ["{}: {}".format(len(self.lastlinks)-i,j) for i,j in enumerate(dispList)] 
	
		box = listInput(self.screen, dispList, drawMode)
		setattr(box,'onenter',newLine(box,self))
		setattr(box,'onKEY_RESIZE',resize(box,self))
		#direct input away from normal input
		box.loop()
	
		curses.curs_set(1)
		self.chat.debounce = False
		self.chat.redraw()
		
	#threaded function that prints the current time every 10 minutes
	#also handles erasing blurbs
	def timeloop(self):
		i = 0
		while True:
			time.sleep(2)
			i+=1
			if time.time() - self.lastBlurb > 4:
				self.printBlurb()
			#every 600 seconds
			if not i % 300:
				self.printTime()
				i=0
				
	def stop(self):
		self.screen.ungetch(27)

#generic wrapper for redrawing listinputs
def resize(self,replace):
	def ret():
		y, x = self.screen.getmaxyx()
		replace.onKEY_RESIZE()
		self.makeWindows(y,x)
	return ret

#wrapper for key bindings
def onkey(keyname):
	def wrapper(func):
		if type(keyname) == str:
			setattr(client,"on"+keyname,func)
		else:
			setattr(client,"on"+CURSES_KEYS[keyname],func)
	return wrapper

#wrapper for commands
def command(commandname):
	def wrapper(func):
		commands[commandname] = func
	return wrapper
	
#wrapper for colorers
def colorer(func):
	colorers.append(func)

class DisconnectException(Exception):
	pass

class SizeException(Exception):
	pass
