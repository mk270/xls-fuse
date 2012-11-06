#!/usr/bin/env python

import logging
import os.path

import mapper
import tree_of_xls

from collections import defaultdict
from errno import ENOENT
from stat import S_IFDIR, S_IFLNK, S_IFREG
from sys import argv, exit
from time import time

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

if not hasattr(__builtins__, 'bytes'):
    bytes = str

class Node(object):
    def __init__(self, parent=None):
        self.parent = parent
        self.children = []

    def receive(self, child):
        self.children.append(child)

    def eject(self, child):
        parent = child.parent
        if parent is None:
            assert False or "Attempt to eject child with no parent from a parent"
        assert child in self.children
        self.children.remove(child)
        
    def insert_into(self, parent):
        if self.parent is not None:
            self.remove_from(self.parent)
        parent.receive(self)
        self.parent = parent

    def remove_from(self, parent):
        parent.eject(self)
        self.parent = None

    def get_children(self):
        return self.children

    def get_parent(self):
        return self.parent

class FSNode(Node):
    def __init__(self, name, mode, nlink):
        super(FSNode, self).__init__()
        now = time()
        self.name = name
        self.mode = mode
        self.change_time = now
        self.modify_time = now
        self.access_time = now
        self.nlink = nlink

    def as_dict(self):
        return dict(st_mode=self.mode, 
                    st_ctime=self.change_time,
                    st_mtime=self.modify_time,
                    st_atime=self.access_time,
                    st_nlink=self.nlink)

    def receive(self, child):
        super(FSNode, self).receive(child)
        self.nlink += 1

    def eject(self, child):
        super(FSNode, self).eject(child)
        self.nlink -= 1
        
    def set_access_time(self, t):
        self.access_time = t

    def set_modify_time(self, t):
        self.modify_time = t

class FSRoot(FSNode):
    def __init__(self):
        super(FSRoot, self).__init__('', S_IFDIR | 0755, 2)

class FSDir(FSNode):
    def __init__(self, name, mode, parent):
        super(FSDir, self).__init__(name, S_IFDIR | mode, 2)
        self.insert_into(parent)

class FSFile(FSNode):
    def __init__(self, name, mode, parent, data):
        super(FSFile, self).__init__(name, S_IFREG | mode, 1)
        self.insert_into(parent)
        self.data = data
        self.st_size = len(data)

    def as_dict(self):
        stat = super(FSFile, self).as_dict()
        stat['st_size'] = self.st_size
        return stat

    def receive(self, child):
        assert False

    def read(self, size, offset):
        return self.data[offset : (offset + size)]

    def write(self, data, offset):
        self.data = self.data[:offset] + data
        self.st_size = len(self.data)
        return len(data)

    def truncate(self, length):
        self.data = self.data[:length]
        self.st_size = length

class Memory(LoggingMixIn, Operations):
    'Example memory filesystem. Supports only one level of files.'

    def __init__(self, contents):
        self.fd = 0
        self.tree = FSRoot()

        def visit(path, subtree):
            for name,value in subtree.iteritems():
                nodename = os.path.join(path, name)

                if type(value) == str:
                    self.create(nodename, 0644)
                    self.write(nodename, value, 0, None)
                elif type(value) == dict:
                    self.mkdir(nodename, 0755)
                    visit(nodename, value)
                else:
                    logging.info(type(value))
                    assert False

        visit('/', contents)

    def namei(self, name):
        logging.info("namei(%s)" % name)
        parts = name.split('/')
        if parts[0] != '':
            raise FuseOSError(ENOENT)

        del(parts[0])

        # strip trailing slash
        if parts[-1] == '':
            parts.pop()

        if len(parts) == 0:
            return self.tree

        node = self.tree

        for name in parts:
            logging.info("namei seek(%s)" % name)
            found = False
            for child in node.get_children():
                if name == child.name:
                    node = child
                    found = True
                    break
            if not found:
                raise FuseOSError(ENOENT)
        logging.info("found")
        return node

    chmod = None
    chown = None

    def create(self, path, mode):
        node, filename = self.mknod(path)
        new_node = FSFile(filename, mode, node, '')

        self.fd += 1
        return self.fd

    def new_file(self, mode):
        now = time()
        return dict(st_mode=(S_IFREG | mode), st_nlink=1,
                    st_size=0, st_ctime=now, st_mtime=now,
                    st_atime=now)

    def getattr(self, path, fh=None):
        logging.info("getattr(%s)" % path)
        node = self.namei(path)

        d = node.as_dict()
        logging.info(repr(d))
        return d

    def getxattr(self, path, name, position=0):
        logging.info("in getxattr")
        return ''

    def listxattr(self, path):
        attrs = self.files[path].get('attrs', {})
        return attrs.keys()

    def mknod(self, path):
        assert not path.endswith("/")
        assert path.startswith("/")
        assert "/" in path
        parts = path.split("/")
        filename = parts[-1]
        parts.pop()
        logging.info(repr(parts))

        if parts == ['']:
            dir_name = '/'
        else:
            dir_name = '/'.join(parts) # thanks a lot, python

        return self.namei(dir_name), filename

    def mkdir(self, path, mode):
        node, filename = self.mknod(path)
        new_node = FSDir(filename, mode, node)

    def open(self, path, flags):
        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        node = self.namei(path)
        return node.read(size, offset)

    def readdir(self, path, fh):
        logging.info("readdir")
        node = self.namei(path)
        names = [ n.name for n in node.get_children() ]
        return ['.', '..'] + names

    def readlink(self, path):
        return self.data[path]

    def removexattr(self, path, name):
        attrs = self.files[path].get('attrs', {})

        try:
            del attrs[name]
        except KeyError:
            pass        # Should return ENOATTR

    def rename(self, old, new):
        self.files[new] = self.files.pop(old)

    def rmdir(self, path):
        node = self.namei(path)
        assert 0 == len(node.get_children())
        node.remove_from(node.get_parent())

    setxattr = None

    def statfs(self, path):
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    symlink = None

    def truncate(self, path, length, fh=None):
        node = self.namei(path)
        node.truncate(length)

    def unlink(self, path):
        node = self.namei(path)
        node.remove_from(node.get_parent())

    def utimens(self, path, times=None):
        node = self.namei(path)

        now = time()
        atime, mtime = times if times else (now, now)
        node.set_access_time(atime)
        node.set_modify_time(mtime)

    def write(self, path, data, offset, fh):
        node = self.namei(path)
        return node.write(data, offset)

if __name__ == '__main__':
    if len(argv) != 3:
        print('usage: %s <xls_filename> <mountpoint>' % argv[0])
        exit(1)

    _, xls_filename, mountpoint = argv

    contents = tree_of_xls.Spreadsheet(xls_filename).tree()

    fs = Memory(contents)
    fuse = FUSE(fs, mountpoint, foreground=True, allow_other=True)
