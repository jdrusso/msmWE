#!/bin/bash
#SBATCH --job-name=mWE_flux_MODELNAME_N_CLUSTERS
#SBATCH --nodes=1 #number of nodes requested
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --tasks=1
#SBATCH --mem-per-cpu=8G
#SBATCH --partition=exacloud #exacloud # available: smp, high-mem, opa, gtx1080, titanx, k40
#SBATCH --output=mWE_flux_MODELNAME_N_CLUSTERS.out
#SBATCH --error=mWE_flux_MODELNAME_N_CLUSTERS.error
#SBATCH --time=36:00:00
PATH=/home/groups/ZuckermanLab/copperma/anaconda3/bin:$PATH
source activate py3
SLURM_SCRATCH=/home/groups/ZuckermanLab/copperma/msmWE/NTL9/gamma05ps/pca/times
cd $SLURM_SCRATCH
fileSpecifier=\'/home/groups/ZuckermanLab/copperma/msmWE/NTL9/gamma05ps/westfiles/west_run*h5\'
refPDBfile=/home/groups/ZuckermanLab/copperma/msmWE/NTL9/reference.pdb
initPDBfile=/home/groups/ZuckermanLab/copperma/msmWE/NTL9/coor0.pdb
#modelName=NTL9_Run${runNumber}
modelName=NTL9_gamma05ps_pca
n_clusters=10000
last_iter=400
python run_msmWE_flux.py \'$fileSpecifier\' $refPDBfile $initPDBfile $modelName $n_clusters $last_iter
