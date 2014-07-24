from __future__ import division
from __future__ import print_function
from minard import app
from flask import render_template, jsonify, request, redirect, url_for
from itertools import product
import time
from redis import Redis
from os.path import join
import json
from tools import total_seconds, parseiso
import requests
from collections import deque, namedtuple
from timeseries import get_timeseries, get_interval

class Program(object):
    def __init__(self, name, machine=None, link=None, description=None, expire=10):
        self.name = name
        self.machine = machine
        self.link = link
        self.description = description
        self.expire = expire

redis = Redis()

PROGRAMS = [Program('builder','builder1.sp.snolab.ca',
                    description="event builder"),
            Program('L2-server','builder1.sp.snolab.ca',
                    description="builder -> buffer transfer"),
            Program('L2-client','buffer1.sp.snolab.ca',
                    description="L2 processor"),
            Program('L2-convert','buffer1.sp.snolab.ca',
                    description="zdab -> ROOT conversion"),
            Program('dataflow',
                    link='http://snoplus.westgrid.ca:5984/buffer/_design/buffer/index.html'),
            Program('builder_copy', 'buffer1.sp.snolab.ca',
                    description="builder -> buffer transfer"),
            Program('buffer_copy', 'buffer1.sp.snolab.ca',
                    description="buffer -> grid transfer"),
            Program('builder_delete', 'buffer1.sp.snolab.ca',
                    description="builder deletion script"),
            Program('PCA','nino.physics.berkeley.edu',
                    link='http://snopluspmts.physics.berkeley.edu/pca')]

PROGRAM_DICT = dict((p.name, p) for p in PROGRAMS)

@app.route('/status')
def status():
    return render_template('status.html', programs=PROGRAMS)

@app.route('/get_status')
def get_status():
    if 'name' not in request.args:
        return 'must specify name', 400

    name = request.args['name']

    up = redis.get('uptime:{name}'.format(name=name))

    if up is None:
        uptime = None
    else:
        uptime = int(time.time()) - int(up)

    return jsonify(status=redis.get('heartbeat:{name}'.format(name=name)),uptime=uptime)

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    """Log heartbeat."""
    if 'name' not in request.form:
        return "must specify name\n", 400

    name = request.form['name']

    if 'status' not in request.form:
        return "must specify status\n", 400

    status = request.form['status']

    try:
        expire = PROGRAM_DICT[name].expire
    except KeyError:
        return "unknown name\n", 400

    # expire every expire seconds
    redis.setex('heartbeat:{name}'.format(name=name),status,expire)

    up = redis.get('uptime:{name}'.format(name=name))

    if up is None:
        redis.setex('uptime:{name}'.format(name=name),int(time.time()),expire)
    else:
        # still running, update expiration
        redis.expire('uptime:{name}'.format(name=name),expire)

    return 'ok\n'

@app.route('/view_log/<name>')
def view_log(name):
    return render_template('view_log.html', name=name)

@app.route('/log', methods=['POST'])
def log():
    """Forward a POST request to the log server at port 8081."""
    resp = requests.post('http://127.0.0.1:8081', headers=request.headers, data=request.form)
    return resp.content, resp.status_code, resp.headers.items()

@app.route('/tail')
def tail():
    name = request.args.get('name', None)

    if name is None:
        return 'must specify name', 400

    seek = request.args.get('seek', None, type=int)

    filename = join('/var/log/snoplus', name + '.log')

    try:
        f = open(filename)
    except IOError:
        return "couldn't find log file {filename}".format(filename=filename), 400

    if seek is None:
        # return last 100 lines
        lines = deque(f, maxlen=100)
    else:
        pos = f.tell()
        f.seek(0,2)
        end = f.tell()
        f.seek(pos)

        if seek > end:
            # log file rolled over
            try:
                prev_logfile = open(filename + '.1')
                prev_logfile.seek(seek)
                # add previous log file lines
                lines = prev_logfile.readlines()
            except IOError:
                return 'seek > log file length', 400

            # add new lines
            lines.extend(f.readlines())
        else:
            # seek to last position and readlines
            f.seek(seek)
            lines = f.readlines()

    return jsonify(seek=f.tell(), lines=list(lines))

@app.route('/')
def index():
    return redirect(url_for('snostream'))

@app.route('/supervisor')
@app.route('/supervisor/<path:path>')
def supervisor(path=None):
    if path is None:
        return redirect(url_for('supervisor', path='index.html'))

    resp = requests.get('http://127.0.0.1:9001' + request.full_path[11:])
    return resp.content, resp.status_code, resp.headers.items()

@app.route('/doc/')
@app.route('/doc/<filename>')
@app.route('/doc/<dir>/<filename>')
@app.route('/doc/<dir>/<subdir>/<filename>')
def doc(dir='', subdir='', filename='index.html'):
    path = join('doc', dir, subdir, filename)
    return app.send_static_file(path)

@app.route('/snostream')
def snostream():
    if not request.args.get('step'):
        return redirect(url_for('snostream',step=1,height=20,_external=True))
    step = request.args.get('step',1,type=int)
    height = request.args.get('height',40,type=int)
    return render_template('snostream.html',step=step,height=height)

@app.route('/nhit')
def nhit():
  return render_template('nhit.html')

@app.route('/l2_filter')
def l2_filter():
    if not request.args.get('step'):
        return redirect(url_for('l2_filter',step=1,height=20,_external=True))
    step = request.args.get('step',1,type=int)
    height = request.args.get('height',40,type=int)
    return render_template('l2_filter.html',step=step,height=height)

@app.route('/detector')
def detector():
    return render_template('detector.html')

@app.route('/daq/<name>')
def channels(name):
    if name == 'cmos':
        return render_template('channels.html', name=name, threshold=5000)
    elif name == 'base':
        return render_template('channels.html', name=name, threshold=80)

@app.route('/alarms')
def alarms():
    return render_template('alarms.html')

CHANNELS = [crate << 9 | card << 5 | channel \
            for crate, card, channel in product(range(20),range(16),range(32))]

@app.route('/query')
def query():
    name = request.args.get('name','',type=str)

    if name == 'dispatcher':
        return jsonify(name=redis.get('dispatcher'))

    if name == 'nhit':
        start = request.args.get('start',type=parseiso)

        now = int(time.time())

        p = redis.pipeline()
        for i in range(start,now):
            p.lrange('ev:1:{ts}:nhit'.format(ts=i),0,-1)
        nhit = sum(p.execute(),[])
        return jsonify(value=nhit)

    if name == 'occupancy':
        now = int(time.time())

        occ = []
        p = redis.pipeline()
        for channel in CHANNELS:
            p.get('ev:60:{0:d}:pmt:{1:d}'.format(now//60-1,channel))
        occ = p.execute()

        count = redis.get('ev:60:{0:d}:count'.format(now//60-1))

        if count is not None:
            count = int(count)
        else:
            count = 0

        occ = [int(n)/count if n else 0 for n in occ]

        return jsonify(values=occ)

    if name == 'cmos' or name == 'base':
        p = redis.pipeline()
        for index in CHANNELS:
            p.get('%s:%i:value' % (name,index))
        values = p.execute()

        return jsonify(value=values)

@app.route('/get_alarm')
def get_alarm():
    try:
        count = int(redis.get('alarms:count'))
    except TypeError:
        redis.set('alarms:count',0)
        return jsonify(alarms=[],latest=-1)

    if 'start' in request.args:
        start = request.args.get('start',type=int)

        if start < 0:
            start = max(0,count + start)
    else:
        start = max(count-100,0)

    alarms = []
    for i in range(start,count):
        value = redis.get('alarms:{0:d}'.format(i))

        if value:
            alarms.append(json.loads(value))

    return jsonify(alarms=alarms,latest=count-1)

@app.route('/metric')
def metric():
    """Returns the time series for argument `expr` as a JSON list."""
    args = request.args

    expr = args['expr']
    start = args.get('start',type=parseiso)
    stop = args.get('stop',type=parseiso)
    now_client = args.get('now',type=parseiso)
    step = args.get('step',type=int)

    now = int(time.time())

    # adjust for clock skew
    dt = now_client - now
    start -= dt
    stop -= dt

    if expr in ('gtid', 'run', 'subrun', 'heartbeat','l2-heartbeat'):
        values = get_timeseries(expr,start,stop,step)
        return jsonify(values=values)

    if expr == u"0\u03bd\u03b2\u03b2":
        import random
        total = get_timeseries('TOTAL',start,stop,step)
        values = [int(random.random() < step/315360) if i else 0 for i in total]
        return jsonify(values=values)

    if '-' in expr:
        # e.g. PULGT-nhit, which means the average nhit for PULGT triggers
        # this is not a rate, so we divide by the # of PULGT triggers for
        # the interval instead of the interval length
        trig, _ = expr.split('-')
        values = get_timeseries(expr,start,stop,step)
        counts = get_timeseries(trig,start,stop,step)
        values = [float(a)/int(b) if a and b else 0 for a, b in zip(values,counts)]
    else:
        values = get_timeseries(expr,start,stop,step)
        interval = get_interval(step)
        values = map(lambda x: int(x)/interval if x else 0, values)

    return jsonify(values=values)

