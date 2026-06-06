#accelerated point update
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from sklearn.ensemble import IsolationForest


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


    blink_interval_s = np.random.normal(loc=4.5, scale=1.5, size=num_samples)
    blink_intervals_s = np.clip(blink_interval_s, 1, 8)

    pupil_size_mm = np.round(pupil_size_mm, 2)
    blink_intervals_s = np.round(blink_intervals_s, 1)
    return np.column_stack((pupil_size_mm, blink_intervals_s))


eye_data_df = generate_eye_data(num_samples=200, seed=42)
n_estimators = 100 # Number of trees

sample_size = 64  # Number of samples used to train each tree
iso_forest = IsolationForest(n_estimators=n_estimators,
                            contamination=0.1,
                            max_samples=sample_size,
                            random_state=42)
std_dev_ps=np.std(eye_data_df[:,0])
std_dev_ibi=np.std(eye_data_df[:,1])
mean_ps=np.mean(eye_data_df[:,0])
mean_ibi=np.mean(eye_data_df[:,1])
z_score=np.column_stack(((eye_data_df[:,0]-mean_ps)/std_dev_ps,(eye_data_df[:,1]-mean_ibi)/std_dev_ibi))
iso_forest.fit(z_score)
t=0

fig = plt.figure(num="Anomaly Detection")
ax = fig.add_subplot(projection="3d")
ax.set_xlim(-5, 5)
ax.set_ylim(-5, 5)
ax.set_zlim(0, 1)
ax.grid(False)
ax.set_xlabel("PA z-score")
ax.set_ylabel("IBI z-score")
ax.set_zlabel("Anomaly Score")
#train_score = iso_forest.decision_function(eye_data_df) * -1 + 1
training_points = ax.scatter(z_score[:, 0], z_score[:, 1], 0, c="gainsboro", label="Training Data", alpha=0.6,marker="o")

np.random.seed(32)
for i in range(200):
    pupil_size_mm = np.clip(np.random.normal(4.5-t*3, 1.0), 0,10 )
    blink_intervals_s = np.clip(np.random.normal(4.5+t*3, 1.5), 1, 12) 
    z_score_ps=(pupil_size_mm-mean_ps)/std_dev_ps
    z_score_ibi=(blink_intervals_s-mean_ibi)/std_dev_ibi

    score = (iso_forest.decision_function([[z_score_ps, z_score_ibi]])[0])
    ax.scatter(z_score_ps, z_score_ibi, score*(-1)+0.3, c=score*(-1)+0.3, cmap="Reds", vmin=0, vmax=0.7, marker="o", s=50)

    fig.canvas.flush_events()
    plt.pause(0.1)
    t += 0.005
