from app.domains.validators.dc_bias_validator import ComponentSet, DCBiasValidator
import pprint

c = ComponentSet(
    R1=180000.0,
    R2=30000.0,
    RC=11000.0, # RC_S1 
    RE=560.0,   # RE_S1 
    VCC=24.0,
    beta=100.0,
    topology="common_emitter"
)
validator = DCBiasValidator()
res = validator.validate(c, gain_target=None)
print("DC PASS:", res.passed)
pprint.pprint(res.errors)
pprint.pprint(res.metrics)

