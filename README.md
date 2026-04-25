# Watermark GIMP filter
Semplice filtro in python per applicare un watermark testuale completamente personalizzato in GIMP.

Questo filtro è stato programmato per le versioni GIMP 3.x. Probabilmente non funziona con GIMP 2.x </br>
Al momento l'ho testato solo sulla mia versione: ***GIMP 3.2.4***

## INSTALLAZIONE ##

Scaricare il file.py </br>
Copiare il file nella cartella dei plug-in di GIMP creando una nuova cartella al suo interno con il nome del plug-in stesso:

Su Linux il percorso è: </br>
~/.config/GIMP/3.2/plug-ins/watermark_filter/watermark_filter.py  (**← il file scaricato**)

Su Windows il percorso è:</br>
%APPDATA%\GIMP\3.2\plug-ins\watermark_filter\watermark_filter.py

Una volta scaricato e copiato il file nella cartella corretta, su Linux e Mac bisogna rendere il file eseguibile (non avendo un PC Windows non ho potuto testare se si debba fare la stessa cosa anche per questo OS):

bash: </br>
chmod +x watermark_filter.py

Fato questo, riavvia GIMP → trovi il filtro in Filtri › Watermark › Aggiungi Watermark…


## ATTENZIONE ##
Il plug-in GIMP 3 deve stare in una cartella il cui nome ***coincide*** con quello del file .py

