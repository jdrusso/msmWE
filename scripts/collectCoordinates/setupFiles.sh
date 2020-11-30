#!/bin/bash
i=1
N=20
outFolder=/home/groups/ZuckermanLab/copperma/msmWE/proteinG/proteinG_amber1D_rw1bUA_1D/westfiles
pathtoWE=/home/groups/ZuckermanLab/copperma/WEsim/proteinG_amber1D/rw1b_1D
if [ -d $outFolder ]
then
    echo "directory ${outFolder} already exists ..."
else
    mkdir $outFolder
    echo "creating directory ${outFolder} ..."
fi

#while [ $i -le $N ]
for i in 1 4 5 6 15 16 17 18 19 7 8 9 10 11 12 #1 2 3 4 5 6 7 8 9 10 11 12 17 18 19
do
    printf -v crunNumber "%02d" $i
    runFileOrig=${pathtoWE}/proteinG_rw1b_1D_aug28_${i}/west_backup.h5
    runFileOut=${outFolder}/west_run${i}.h5
    if [ -e $runFileOut ]
    then
        echo "WestFile ${runFileOut} already exists ..."
    else
        cp $runFileOrig $runFileOut
        echo "copied WestFile ${runFileOrig} to ${runFileOut}"
    fi
    refPDBfile=/home/groups/ZuckermanLab/copperma/msmWE/proteinG/reference.pdb
    initPDBfile=/home/groups/ZuckermanLab/copperma/msmWE/proteinG/coor0.pdb
    modelName=proteinG_rw1_Run${i}
    #WEfolder=${pathtoWE}/Run${crunNumber}
    WEfolder=${pathtoWE}/proteinG_rw1b_1D_aug28_${i}
    fileSpecifier=$runFileOut
    sed "s%REFPDBFILE%$refPDBfile%g" BLANKrun-cc.slurm > run-cc${i}.slurm
    sed -i "s%INITPDBFILE%$initPDBfile%g" run-cc${i}.slurm
    sed -i "s%MODELNAME%$modelName%g" run-cc${i}.slurm
    sed -i "s%WEFOLDER%$WEfolder%g" run-cc${i}.slurm
    sed -i "s%OUTFOLDER%$outFolder%g" run-cc${i}.slurm
    sed -i "s%FILESPECIFIER%$fileSpecifier%g" run-cc${i}.slurm
    #sh run-cc${i}.slurm
    sbatch run-cc${i}.slurm >> jobnumbers.txt
#    i=$(( $i+1 ))
done


