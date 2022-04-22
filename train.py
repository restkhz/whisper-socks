import zstandard as zstd
import os

path = './samples'
files = os.listdir(path)

print('Reading ./samples...')

samples = []

for f in files:
        _f = open(path+'/'+f, 'rb')
        samples.append(_f.read())

print('Samples Loaded. Start training...')

cmp_dict = zstd.train_dictionary(524288, samples, threads=-1).as_bytes()

print('Training finished.')

f = open('./dict', 'wb')
f.write(cmp_dict)
f.close()

print('Dict saved at ./dict\a')
