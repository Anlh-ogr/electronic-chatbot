# coding=utf-8
import codecs

with codecs.open('app/domains/circuits/builder/bjt.py', 'r', 'utf-8') as f:
    text = f.read()

import re

# Fix CE NETS
old_ce_nets = '''        # VBIAS net: R1 du?i + R2 trên + input coupling
        vbias_pins = [PinRef("R1", "2"), PinRef("R2", "1")]
        if has_cin:
            vbias_pins.append(PinRef("CIN", "2"))
        else:
            vbias_pins.append(PinRef("Q1", "B"))
        self.nets["VBIAS"] = Net("VBIAS", tuple(vbias_pins))

        # VIN net (n?u có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))
            self.nets["_VIN_INTERNAL"] = Net("_VIN_INTERNAL", (
                PinRef("CIN", "2"),
                PinRef("Q1", "B")
            ))'''

new_ce_nets = '''        # VBIAS net: R1 du?i + R2 trên + input coupling
        vbias_pins = [PinRef("R1", "2"), PinRef("R2", "1"), PinRef("Q1", "B")]
        if has_cin:
            vbias_pins.append(PinRef("CIN", "2"))
        self.nets["VBIAS"] = Net("VBIAS", tuple(vbias_pins))

        # VIN net (n?u có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))'''

text = text.replace(old_ce_nets, new_ce_nets)

# Fix CC NETS
old_cc_nets_vbias = '''        # VBIAS net: gi?ng CE
        vbias_pins = [PinRef("R1", "2"), PinRef("R2", "1")]
        if has_cin:
            vbias_pins.append(PinRef("CIN", "2"))
        else:
            vbias_pins.append(PinRef("Q1", "B"))
        self.nets["VBIAS"] = Net("VBIAS", tuple(vbias_pins))

        # VIN net (n?u có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))
            self.nets["_VIN_INTERNAL"] = Net("_VIN_INTERNAL", (
                PinRef("CIN", "2"),
                PinRef("Q1", "B")
            ))'''

new_cc_nets_vbias = '''        # VBIAS net: gi?ng CE
        vbias_pins = [PinRef("R1", "2"), PinRef("R2", "1"), PinRef("Q1", "B")]
        if has_cin:
            vbias_pins.append(PinRef("CIN", "2"))
        self.nets["VBIAS"] = Net("VBIAS", tuple(vbias_pins))

        # VIN net (n?u có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))'''

text = text.replace(old_cc_nets_vbias, new_cc_nets_vbias)

with codecs.open('app/domains/circuits/builder/bjt.py', 'w', 'utf-8') as f:
    f.write(text)

print("Patcher run.")
