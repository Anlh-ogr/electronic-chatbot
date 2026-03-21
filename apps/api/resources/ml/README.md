# XGBoost topology/block training

Train models from metadata:

```powershell
cd apps/api
python resources/ml/train_xgboost_topology_block.py
```

Artifacts are written to `resources/ml_models`:

- `xgb_topology_model.json`
- `xgb_block_model.json`
- `xgb_feature_schema.json`
- `xgb_training_report.json`

The runtime planner auto-loads these files if present and blends ML scores with rule-based scoring.
