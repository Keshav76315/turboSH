import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.neighbors import LocalOutlierFactor
from sklearn.model_selection import GridSearchCV
from sklearn.metrics import make_scorer, f1_score, classification_report
import joblib
import os
import warnings

# Suppress warnings for cleaner output
warnings.filterwarnings("ignore")

print("Loading dataset...")
df = pd.read_csv("datasets/synthetic_traffic_dataset.csv")
X = df.drop(columns=["label"])
y = df["label"]  # 0 = normal, 1 = attack

print(f"Dataset shape: {X.shape}")


# Custom Scorer for GridSearchCV
# Sklearn anomaly models output 1 for normal, -1 for anomaly. We map -1 to 1 (attack) and 1 to 0 (normal)
def anomaly_f1_score(y_true, y_pred):
    y_pred_mapped = np.where(y_pred == -1, 1, 0)
    return f1_score(y_true, y_pred_mapped)


scorer = make_scorer(anomaly_f1_score)

# Define models and their hyperparameter grids to search
models = {
    "IsolationForest": {
        "estimator": IsolationForest(random_state=42, n_jobs=-1),
        "params": {
            "n_estimators": [100, 200],
            "contamination": ["auto", 0.05, 0.09, 0.12],
            "max_samples": ["auto", 256],
        },
    },
    "OneClassSVM": {
        "estimator": OneClassSVM(),
        "params": {
            "kernel": ["rbf"],
            "nu": [0.05, 0.09, 0.12],
            "gamma": ["scale", "auto"],
        },
    },
    # LOF must have novelty=True to be used for predicting on new, unseen data in the future
    "LocalOutlierFactor": {
        "estimator": LocalOutlierFactor(novelty=True, n_jobs=-1),
        "params": {
            "n_neighbors": [20, 50],
            "contamination": ["auto", 0.05, 0.09, 0.12],
        },
    },
}

best_models = {}

print("\nStarting Hyperparameter Tuning with GridSearchCV...")
print("This may take a minute or two depending on your CPU.\n")

for name, config in models.items():
    print(f"--- Tuning {name} ---")
    # cv=3 means 3-fold cross validation
    grid = GridSearchCV(
        config["estimator"],
        config["params"],
        scoring=scorer,
        cv=3,
        n_jobs=-1,
        verbose=1,
    )
    grid.fit(X, y)
    best_models[name] = grid

    # Evaluate best model on the full dataset
    best_model = grid.best_estimator_
    y_pred = best_model.predict(X)
    y_pred_mapped = np.where(y_pred == -1, 1, 0)

    print(f"[{name}] Best Parameters Found:")
    for param, value in grid.best_params_.items():
        print(f"  > {param}: {value}")
    print(f"[{name}] Cross-Validated F1 Score: {grid.best_score_:.4f}")
    print(f"[{name}] Classification Report (Full Dataset):")
    print(
        classification_report(
            y, y_pred_mapped, target_names=["Normal (0)", "Attack (1)"]
        )
    )
    print("-" * 50)

# Compare and select the absolute best model
print("\n========================================================")
print("FINAL MODEL SUMMARY (Equivalent to model.summary())")
print("========================================================")
best_overall_name = max(best_models, key=lambda k: best_models[k].best_score_)
best_overall_grid = best_models[best_overall_name]
best_estimator = best_overall_grid.best_estimator_

print(f"Selected Model       : {best_overall_name}")
print(f"Hyperparameters      : {best_overall_grid.best_params_}")
print(f"Validation F1 Score  : {best_overall_grid.best_score_:.4f}\n")

print("Model Attributes & Structure:")
print(f" - Input Features ({X.shape[1]}): {list(X.columns)}")

if best_overall_name == "IsolationForest":
    print(f" - Total Trees (n_estimators): {best_estimator.n_estimators}")
    print(f" - Max Samples per Tree    : {best_estimator.max_samples_}")
    print(f" - Target Contamination    : {best_estimator.contamination}")
elif best_overall_name == "OneClassSVM":
    print(f" - SVM Kernel              : {best_estimator.kernel}")
    print(f" - Gamma Function          : {best_estimator.gamma}")
    print(f" - Nu (Anomaly Cap)        : {best_estimator.nu}")
    print(f" - Support Vectors Used    : {len(best_estimator.support_)}")
elif best_overall_name == "LocalOutlierFactor":
    print(f" - Neighbors Considered    : {best_estimator.n_neighbors_}")
    print(f" - Leaf Size               : {best_estimator.leaf_size}")
    print(f" - Target Contamination    : {best_estimator.contamination}")

# Save the scikit-learn model
os.makedirs("models", exist_ok=True)
joblib_path = f"models/best_{best_overall_name.lower()}.pkl"
joblib.dump(best_estimator, joblib_path)
print(f"\n✅ Training complete! Best model saved to {joblib_path}")
print("========================================================")
