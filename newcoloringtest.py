import chatango
import client.display as disp

import sys
from timecomp import printmeta

chatango.chatbot = type('whocares',(object,),{"members":  ['cubebert','namefag0','ayanamiko','chamomileable','gondolabigduck','drrindou','rvnx','bertyo','salazar84','memestialmemeizer']})

def defaultcolor(msg,*args):
	msg.default = chatango.getColor(args[0])
def greentext(msg,*args):
	#match group 3 (the message sans leading replies)
	msg.colorByRegex(chatango.LINE_RE,lambda x: x[0] == '>' and 11 or None,3,'')
def link(msg,*args):
	msg.colorByRegex(chatango.linkopen.LINK_RE,disp.rawNum(0),1)
def names(msg,*args):
	def check(group):
		name = group.lower()[1:]
		if name in chatango.chatbot.members:
			return chatango.getColor(name)
		return ''
	msg.colorByRegex(chatango.REPLY_RE,check)
def quotes(msg,*args):
	msg.effectByRegex(chatango.QUOTE_RE,'underline')
def chatcolors(msg,*args):
	args[1] and msg.addGlobalEffect('reverse')	#reply
	args[2] and msg.addGlobalEffect('underline')	#history
	msg.insertColor(0)		#make sure we color the name right
	(' ' + msg).insertColor(0,args[3]+12)	#channel

old = [defaultcolor,greentext,link,names,quotes,chatcolors]

repeat = 10
if len(sys.argv) > 1:
	repeat = int(sys.argv[1])

data = []
with open("testdata") as stringsfile:
	data.extend(stringsfile.read().split("\n"))

def oldcoloring(dat):
	for b in dat:
		c = disp.coloringold(b)
		for i in old:
			i(c,"cubebert",False,False,0)		#i don't care enough to actually calculate the slice of the name
		disp.breaklines(str(c),50,'    ')

def newcoloring(dat):
	for b in dat:
		c = disp.coloring(b)
		for i in chatango.overlay._colorizers:
			i(c,"cubebert",False,True,0)
		c.breaklines(50,'    ')

'''
if len(sys.argv) == 2:
	msg = data[int(sys.argv[-1])]
	print(msg,msg.find("\t"))
	input()
	msg = disp.coloring(msg.replace("\t","\n"))
	print('(effect,color)')
	for i in chatango.overlay._colorizers:
		i(msg,"memestialmemeizer",False,False,0)
		print(' '.join(map(lambda x: repr((bin(x&15), (x >> 4)-1)),msg.formatting)))
	print('\n'.join(msg.breaklines(50,'    ')[0]))

else:
	for b in data:
		b = b.replace("\t","\n")
		oldc = disp.coloringold(b)
		newc = disp.coloring(b)
		for i in old:
			i(oldc,"memestialmemeizer",False,False,0)		#i don't care enough to actually calculate the slice of the name
		for i in chatango.overlay._colorizers:
			i(newc,"memestialmemeizer",False,False,0)
		

		print('\n'.join(disp.breaklines(str(oldc),50,'    ')[0]))
		print('\n'.join(newc.breaklines(50,'    ')[0]))
		input()
'''

printmeta(oldcoloring,newcoloring,data,repeat=repeat,scale = 1000000)
