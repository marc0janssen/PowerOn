#!/bin/sh

# F4:4D:30:6A:AF:77 - Eridu
# 1C:69:7A:6F:D4:4B - Uruk
# 94:C6:91:AA:6D:CE - Larak

URUK="1C:69:7A:6F:D4:4B"
ERIDU="F4:4D:30:6A:AF:77"
LARAK="94:C6:91:AA:6D:CE"

/usr/bin/wakeonlan ${URUK} ${LARAK} ${ERIDU}
