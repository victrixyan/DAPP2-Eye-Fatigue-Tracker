import csv 
import numpy as np
import matplotlib.pyplot as plt
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
import pymannkendall as mk
import copy
ibi_val_train=[]
ps_val_train = []
with open('calibration_data_dp.csv', 'r') as file:
    reader = csv.reader(file)
    for row in reader:
        if row[0] == 'uid':
             continue
        ibi_val_train.append(float(row[2]))
        ps_val_train.append(float(row[3]))
ibi_val_test=[]
ps_val_test = []
with open('test_data_dp.csv', 'r') as file:
    reader = csv.reader(file)
    for row in reader:
        if row[0] == 'uid':
             continue
        ibi_val_test.append(float(row[2]))
        ps_val_test.append(float(row[3]))

def filtering(ibi_values):
    index = []
    prev_ibi=0
    for i in range(1, len(ibi_values) - 1):
        diff = ibi_values[i] - ibi_values[i-1]
        next_diff = ibi_values[i+1] - ibi_values[i]
        if ibi_values[i] <= 0.5:
            continue
        # takes reset 
        elif diff < -0.2 and (next_diff<0.8 or next_diff>1.2):
            index.append(i)
            prev_ibi=ibi_values[i]

        # takes last 0 diff
        elif i > 1 and abs(next_diff) >= 0.2 and abs(diff) <= 0.2 and abs(prev_ibi-ibi_values[i]) >= 0.2:
            index.append(i)
            prev_ibi=ibi_values[i]
        # takes last 1 step diff
        elif 0.75 < diff <= 1.25 and next_diff < 0.20:
            index.append(i)
            prev_ibi=ibi_values[i]

    return index
index_train = filtering(ibi_val_train)
index_test = filtering(ibi_val_test)

pupil_mean_train = []
for i in index_train:
    pupil_mean_train.append(np.mean(ps_val_train[i:i+3]))
for i in index_test:
    if i <= 300:
        pupil_mean_train.append(np.mean(ps_val_test[i:i+3]))
pupil_mean_test = []
for i in index_test  :
    if i > 300:
        pupil_mean_test.append(np.mean(ps_val_test[i:i+3]))
ibi_val_train_f = [ibi_val_train[i] for i in index_train] + [ibi_val_test[i] for i in [x for x in index_test if x <=300]]
ibi_val_test_f = [ibi_val_test[i] for i in index_test if i >300]
eye_data_df = np.column_stack((pupil_mean_train, ibi_val_train_f))
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

fig = plt.figure(num="Anomaly Detection")
ax = fig.add_subplot(projection="3d")
ax.set_xlim(4, 16)
ax.set_ylim(0, 14)
ax.set_zlim(0, 10)
ax.grid(False)
ax.set_xlabel("Pupil Size (mm)")
ax.set_ylabel("Inter-blink Interval (s)")
ax.set_zlabel("Fatigue Score")
eye_data_test_df = np.column_stack((pupil_mean_test, ibi_val_test_f))
training_points = ax.scatter(np.sqrt(eye_data_df[:,0]*(3.4**2)*(10**(-2))/np.pi), eye_data_df[:,1], 0, c="gainsboro", label="Training Data", alpha=0.6,marker="o")


z_score_test=np.column_stack(((eye_data_test_df[:,0]-mean_ps)/std_dev_ps,(eye_data_test_df[:,1]-mean_ibi)/std_dev_ibi))
test_score = iso_forest.decision_function(z_score_test) * -1 + 0.2
mask = (np.sqrt(eye_data_test_df[:,0]*(3.4**2)*(10**(-2))/np.pi) < 16) & (eye_data_test_df[:,1] < 14)
t_points = ax.scatter(np.sqrt(eye_data_test_df[:,0][mask]*(3.4**2)*(10**(-2))/np.pi), eye_data_test_df[:,1][mask], ((test_score[mask]-np.min(test_score))**2/(np.max(test_score)-np.min(test_score))**2)*10, c=((test_score[mask]-np.min(test_score))**2/(np.max(test_score)-np.min(test_score))**2)*10,cmap="Reds", label="Test Data", alpha=0.6,marker="o",vmin=0,vmax=10)



fig1,ax1=plt.subplots(num="Time series data")
ax1.set_xlabel('Time')
ax1.set_ylabel('Test score')

print(mk.original_test(test_score))

ax1.scatter([x-304 for x in index_test if x >300],test_score,color = "black",s=10)
fig2,ax2=plt.subplots(num="Time series data smoothed")
ax2.set_xlabel('Time')
ax2.set_ylabel('Test score')

new_set= [np.mean(test_score[i-4:i+5]) for i in range(4,len(test_score)-4)]
new_set= list(test_score[0:4])+new_set+list(test_score[len(test_score)-4:len(test_score)])
ax2.scatter([x-304 for x in index_test if x >300],new_set,color = "black",s=10)
fig3,ax3= plt.subplots(num="Linear Regression Model")
ax3.set_xlabel('Time')
ax3.set_ylabel('Test score')
x_vals = np.array([x-304 for x in index_test if x > 300]).reshape(-1, 1)

model = LinearRegression()
model.fit(x_vals, test_score)
test_score_pred = model.predict(x_vals)

ax3.scatter(x_vals, test_score_pred)
plt.show()
        
