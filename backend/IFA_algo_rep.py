#visualization of an individual tree of the isolation forest algorithm with lines and zoom 
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from sklearn.ensemble import IsolationForest
import time
plt.ion()
# Parameters
def generate_eye_data(num_samples, seed=42):
    """Generates a DataFrame with realistic synthetic data for pupil size

    and average blink rate.
    """
    # Set seed for reproducibility
    np.random.seed(seed)

    pupil_size_mm = np.random.normal(loc=4.5, scale=1.0, size=num_samples)
    pupil_size_mm = np.clip(pupil_size_mm, 2.0, 8.0)


    blink_rate_bpm = np.random.normal(loc=16.0, scale=3.0, size=num_samples)
    blink_rate_bpm = np.clip(blink_rate_bpm, 8, 28)

    pupil_size_mm = np.round(pupil_size_mm, 2)
    blink_rate_bpm = np.round(blink_rate_bpm, 1)
    return np.column_stack((pupil_size_mm, blink_rate_bpm))


eye_data_df = generate_eye_data(num_samples=200, seed=32)



features=eye_data_df
n_estimators = 100 # Number of trees

sample_size = 64  # Number of samples used to train each tree
# Train Isolation Forest
iso_forest = IsolationForest(n_estimators=n_estimators,
                            contamination="auto",
                            max_samples=sample_size,
                            random_state=42)
iso_forest.fit(features)

anomaly_score = iso_forest.decision_function(features)


#simplified demo for plotting the lines of the decision function

pupil_size_mmp = np.random.normal(loc=4.5, scale=1.0, size=1)
pupil_size_mmp = np.clip(pupil_size_mmp, 2.0, 8.0)


blink_rate_bpmp = np.random.normal(loc=16.0, scale=3.0, size=1)
blink_rate_bpmp= np.clip(blink_rate_bpmp, 8, 28)
point = [pupil_size_mmp[0], blink_rate_bpmp[0]*0.7]
def plot_lines(point,features):
    fig3,ax3 = plt.subplots(num="Decision Function Lines")
    ax3.scatter(features[:, 0], features[:, 1], color="gainsboro", marker="o")
    ax3.set_xlabel('Pupil Size (mm)')
    ax3.set_ylabel('Blink Rate (bpm)')
    ax3.scatter(point[0], point[1], color="red", marker="o", s=100, label='Test Point')
    # mini IFA algorithm to plot the lines of the decision function
    sample_size = 64
    idx = np.random.choice(len(features), size=sample_size, replace=False)
    minisamp = features[idx]
    xmin, xmax = features[:, 0].min(), features[:, 0].max()
    ymin, ymax = features[:, 1].min(), features[:, 1].max()
    n=0
 
    while n<=8:
        if  len(minisamp) <= 0:
            break
        f=np.random.randint(0,2)
        
        if f==0:
            sep= np.random.uniform(xmin, xmax)
            ax3.axvline(x=sep, color='black', linestyle='-')
            if point[f] < sep:
                minisamp = minisamp[minisamp[:,f] < sep]
                xmax = sep
            else:
                minisamp = minisamp[minisamp[:,f] >= sep]
                xmin = sep  
        if f==1:
            sep= np.random.uniform(ymin, ymax)
            ax3.axhline(y=sep, color='black', linestyle='-')
            if point[f] < sep:
                minisamp = minisamp[minisamp[:,f] < sep]
                ymax = sep
            else:
                minisamp = minisamp[minisamp[:,f] >= sep]
                ymin = sep
      
                
        fig3.canvas.flush_events()
        plt.pause(1)
        if f==0:
            if point[f] < sep:
                ax3.set_xlim(xmin, xmax)
            if point[f] >= sep:
                ax3.set_xlim(xmin, xmax)
        if f==1:
            if point[f] < sep:
                ax3.set_ylim(ymin, ymax)
            if point[f] >= sep:
                ax3.set_ylim(ymin, ymax)
        n+=1
        fig3.canvas.flush_events()
        plt.pause(1)

plot_lines(point,features)
