import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import numpy as np
import sys
sys.path.append('/home/groups/ZuckermanLab/copperma/msmWE')
import msmWE
import h5py
import pickle
import os
import subprocess

fileSpecifier=sys.argv[1]
refPDBfile=sys.argv[2]
initPDBfile=sys.argv[3]
modelName=sys.argv[4]
n_clusters=sys.argv[5]
last_iter=sys.argv[6]
n_clusters=int(n_clusters)
last_iter=int(last_iter)

model=msmWE.modelWE()
print('initializing...')
model.initialize(fileSpecifier,refPDBfile,initPDBfile,modelName)
model.WEtargetp1=1.0 #target def on WE p1
model.WEbasisp1_min=9.6 #WE bin where basis structure is mapped- lower edge
model.WEbasisp1_max=12.5 #upper edge
model.pcoord_ndim=1 #number of pcoords
model.n_lag=0
n_lag=model.n_lag
model.dimReduceMethod='pca' #dimensionality reduction method
last_iter_cluster=last_iter #model.maxIter-1 #last iter often not complete
ncoords=100000
i=last_iter_cluster
numCoords=0
coordSet=np.zeros((0,model.nAtoms,3)) #extract coordinate libraries for clustering
pcoordSet=np.zeros((0,model.pcoord_ndim))
while numCoords<ncoords:
    model.get_iter_data(i)
    model.get_iter_coordinates()
    indGood=np.squeeze(np.where(np.sum(np.sum(model.coordList,2),1)!=0))
    coordSet=np.append(coordSet,model.coordList[indGood,:,:],axis=0)
    pcoordSet=np.append(pcoordSet,model.pcoord1List[indGood,:],axis=0)
    numCoords=np.shape(coordSet)[0]
    i=i-1
model.coordSet=coordSet
model.pcoordSet=pcoordSet
first_iter_cluster=i
model.first_iter=first_iter_cluster
model.last_iter=last_iter_cluster
n_coords=np.shape(model.coordSet)[0]

model.dimReduce()

clusterFile=modelName+'_clusters_s'+str(first_iter_cluster)+'_e'+str(last_iter_cluster)+'_nC'+str(n_clusters)+'.h5'
exists = os.path.isfile(clusterFile)
if exists:
    print('loading clusters...')
    model.load_clusters(clusterFile)
else:
    print('clustering '+str(n_coords)+' coordinates into '+str(n_clusters)+' clusters...')
    model.cluster_coordinates(n_clusters)

first_iter=1
model.get_fluxMatrix(n_lag,first_iter,last_iter) #extracts flux matrix, output model.fluxMatrixRaw
model.organize_fluxMatrix() #gets rid of bins with no connectivity, sorts along p1, output model.fluxMatrix
model.get_Tmatrix() #normalizes fluxMatrix to transition matrix, output model.Tmatrix
model.get_steady_state_algebraic() #gets steady-state from eigen decomp, output model.pSS
model.get_steady_state_target_flux() #gets steady-state target flux, output model.JtargetSS
objFile=modelName+'_s'+str(first_iter)+'_e'+str(last_iter)+'_nC'+str(n_clusters)+'.obj'
objFileHandler=open(objFile,'wb')
del model.clusters
pickle.dump(model,objFileHandler)
objFileHandler.close()
