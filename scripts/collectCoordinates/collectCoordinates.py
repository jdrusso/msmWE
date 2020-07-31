import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import numpy as np
import sys
sys.path.append('/home/groups/copperma/ZuckermanLab/msmWE')
import msmWE
import h5py
import pickle
import os
import subprocess
import mdtraj as md

#fileSpecifier='/home/groups/ZuckermanLab/mostofia/ProteinFolding/NTL9/WestPA/Gamma05ps/Pcoord1D/OpenMM/Run03/west_prev.h5'
#refPDBfile='/home/groups/ZuckermanLab/copperma/msmWE/NTL9/reference.pdb'
#initPDBfile='/home/groups/ZuckermanLab/copperma/msmWE/NTL9/coor0.pdb'
#modelName='NTL9_Run03_jan9'
fileSpecifier=sys.argv[1]
refPDBfile=sys.argv[2]
initPDBfile=sys.argv[3]
modelName=sys.argv[4]
WEfolder=sys.argv[5]

model=msmWE.modelWE()
print('initializing...')
model.initialize(fileSpecifier,refPDBfile,initPDBfile,modelName)
model.get_iterations()

f=h5py.File(model.fileList[0],'a')

for n_iter in range(1,model.maxIter+1):
    if n_iter % 10==0:
        sys.stdout.write('copying coords into westfile iteration '+str(n_iter)+'\n')
    nS=model.numSegments[n_iter-1].astype(int)
    coords=np.zeros((nS,2,model.nAtoms,3))
    for iS in range(nS):
        trajpath=WEfolder+"/traj_segs/%06d/%06d" % (n_iter,iS)
        coord0=np.squeeze(md.load(trajpath+'/parent.rst7',top=model.reference_structure.topology)._xyz)
        coord1=np.squeeze(md.load(trajpath+'/seg.rst7',top=model.reference_structure.topology)._xyz)
        coords[iS,0,:,:]=coord0
        coords[iS,1,:,:]=coord1
    dsetName="/iterations/iter_%08d/auxdata/coord" % int(n_iter)
    try:
        dset = f.create_dataset(dsetName, np.shape(coords))
        dset[:] = coords
    except:
        sys.stdout.write('coords exist for iteration '+str(n_iter)+' NOT overwritten\n')

f.close()

        

            
