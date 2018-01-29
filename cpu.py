#!/usr/bin/env python
import psutil
import time
from redis import Redis

redis = Redis()

def log():
    cpu_usage = psutil.cpu_percent()
    mem_usage = psutil.virtual_memory().percent

    now = int(time.time())

    # keys are 'stream/[time interval]:[now//time interval]:[name]'

    # set cpu percent
    redis.set('stream/1:%i:cpu' % now, cpu_usage)
    # set it to expire in 600 seconds
    redis.expire('stream/1:%i:cpu' % now,600)
    # keep a running sum for the minute interval. Later we can divide
    # by the number of points added to get an average.
    redis.incrbyfloat('stream/60:%i:cpu' % (now//60), cpu_usage)
    redis.expire('stream/60:%i:cpu' % (now//60), 60000)
    # keep track of the number of times we incremented the minute total
    redis.incr('stream/60:%i:count' % (now//60))
    redis.expire('stream/60:%i:count' % (now//60), 60000)

    # do the same for memory usage
    # here we'll use a redis pipeline so that the commands aren't sent
    # until the very end
    p = redis.pipeline()
    p.set('stream/1:%i:mem' % now, mem_usage)
    p.expire('stream/1:%i:mem' % now, 600)
    p.incrbyfloat('stream/60:%i:mem' % (now//60), mem_usage)
    p.expire('stream/60:%i:mem' % (now//60), 60000)
    p.incr('stream/60:%i:count' % (now//60))
    p.expire('stream/60:%i:count' % (now//60), 60000)
    p.execute()

if __name__ == '__main__':
    import time

    while True:
        log()
        time.sleep(1)
