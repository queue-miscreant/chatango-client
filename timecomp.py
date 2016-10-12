import time
_COLOR_NAMES =	['black'
				,'red'
				,'green'
				,'yellow'
				,'blue'
				,'magenta'
				,'cyan'
				,'white'
				,''
				,'none']

mean = lambda x: sum(x)/len(x)
variance = lambda x: mean([(i - mean(x))**2 for i in x])

def printcolor(color,*args,**kwargs):
	try:
		i = _COLOR_NAMES.index(color)
	except ValueError:
		raise Exception("color {} not found".format(color))
	print("\x1b[3{}m".format(i),end="")
	print(*args,**kwargs)
	print("\x1b[m",end="")

def analysis(function1,function2,*args):
	now = time.time()
	function1(*args)
	t1 = time.time()-now

	now = time.time()
	function2(*args)
	return t1,time.time()-now

def metaanalysis(*args,**kwargs):
	repeat = 20
	if "repeat" in kwargs:
		repeat = kwargs["repeat"]
	acc = []
	for i in range(repeat):
		acc.append(analysis(*args))
	return tuple(zip(*acc))

def printmeta(*args,**kwargs):
	scale = 1
	if "scale" in kwargs:
		scale = kwargs['scale']
	l = metaanalysis(*args,**kwargs)
	lavg = list(map(mean,l))
	lvar = list(map(variance,l))

	n = args[0].__name__,args[1].__name__
	printcolor('yellow',"Analysis of functions {} and {}".format(n[0],n[1]))
	for i in range(2):
		print("{}:".format(n[i]))
		print("\tmean:\t\t",end="")
		printcolor((lavg[i] == min(lavg)) and 'green' or 'red',lavg[i]*scale)
		print("\tvariance:\t",end="")
		printcolor((lvar[i] == min(lvar)) and 'green' or 'red', lvar[i]*(scale**2))
	
	if (lavg[0] < lavg[1]):
		printcolor('yellow',"{} is {} units faster ({} times more efficient)".format(n[0],(lavg[1]-lavg[0])*scale,lavg[1]/lavg[0]))
	if (lavg[0] > lavg[1]):
		printcolor('yellow',"{} is {} units faster ({} times more efficient)".format(n[1],(lavg[0]-lavg[1])*scale,lavg[0]/lavg[1]))
	else:
		printcolor('yellow',"{} and {} have the same average speeds".format(n[0],n[1]))
	
	if (lvar[0] < lvar[1]):
		printcolor('yellow',"{}'s variance is {} times better".format(n[0],lvar[1]/lvar[0]))
	elif (lvar[0] > lvar[1]):
		printcolor('yellow',"{}'s variance is {} times better".format(n[1],lvar[0]/lvar[1]))
	else:
		printcolor('yellow',"{} and {} have the same variance".format(n[0],n[1])) 
