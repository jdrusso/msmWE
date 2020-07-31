#!/bin/bash
#SBATCH --job-name=mWE_cc
#SBATCH --nodes=1 #number of nodes requested
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=2
#SBATCH --tasks=1
#SBATCH --partition=exacloud # available: smp, high-mem, opa, gtx1080, titanx, k40
#SBATCH --output=mWE_cc.out
#SBATCH --error=mWE_cc.error
#SBATCH --time=36:00:00
PATH=/home/groups/ZuckermanLab/copperma/anaconda3/bin:$PATH
source activate py3
SLURM_SCRATCH=OUTFOLDER
cd $SLURM_SCRATCH
fileSpecifier=FILESPECIFIER
refPDBfile=REFPDBFILE
initPDBfile=INITPDBFILE
modelName=MODELNAME
WEfolder=WEFOLDER

python -i /home/groups/ZuckermanLab/msmWE/collectCoordinates.py $fileSpecifier $refPDBfile $initPDBfile $modelName $WEfolder
