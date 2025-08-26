# ---- Stufe 1: Ghostscript Builder ----
    FROM debian:bullseye AS gs_builder

    # WICHTIG: Passen Sie diese Version an den Dateinamen Ihres heruntergeladenen Tarballs an!
    # Wenn Ihre Datei "ghostscript-10.05.1.tar.gz" heißt, lassen Sie ARG GS_VERSION=10.05.1
    # Wenn Ihre Datei "ghostscript-10.03.1.tar.gz" heißt, setzen Sie ARG GS_VERSION=10.03.1
    ARG GS_VERSION=10.05.1
    
    # Build-Abhängigkeiten für Ghostscript installieren
    # wget und curl sind jetzt optional, da wir die Datei kopieren
    RUN apt-get update && \
        apt-get install -y --no-install-recommends ca-certificates && \
        apt-get install -y --no-install-recommends \
            build-essential \
            tar \
            pkg-config \
            zlib1g-dev \
            libpng-dev \
            libjpeg62-turbo-dev \
            libtiff5-dev \
            libcups2-dev \
            libfontconfig1-dev \
            libidn11-dev \
            libpaper-dev \
            libijs-dev \
            libjbig2dec0-dev \
            libopenjp2-7-dev \
        && update-ca-certificates \
        && rm -rf /var/lib/apt/lists/*
    
    WORKDIR /usr/src
    
    # Kopiere das lokal heruntergeladene Ghostscript-Archiv aus dem Docker Build-Kontext
    # Stellen Sie sicher, dass die Datei "ghostscript-${GS_VERSION}.tar.gz"
    # (z.B. ghostscript-10.05.1.tar.gz) im selben Verzeichnis wie das Dockerfile liegt.
    COPY ghostscript-${GS_VERSION}.tar.gz ./ghostscript_archive.tar.gz
    
    # Ghostscript Quellen entpacken
    RUN echo "Entpacke ghostscript_archive.tar.gz..." && \
        tar -xzf ghostscript_archive.tar.gz && \
        echo "Entpacken abgeschlossen." && \
        rm ghostscript_archive.tar.gz # Entferne das Tarball nach dem Entpacken
    
    # Ghostscript konfigurieren, kompilieren und in einem temporären Verzeichnis installieren
    # Der Name des entpackten Ordners muss mit der Version übereinstimmen
    WORKDIR /usr/src/ghostscript-${GS_VERSION}
    RUN echo "Konfiguriere Ghostscript Version ${GS_VERSION}..." && \
        ./configure \
            --prefix=/usr/local \
            --disable-compile-inits \
            --disable-gtk \
            --without-x \
            --with-ijs \
            --with-jbig2dec \
            --with-openjpeg \
        && echo "Kompiliere Ghostscript (make)..." && \
        make -j$(nproc) \
        && echo "Installiere Ghostscript (make install)..." && \
        make install DESTDIR=/app/gs_install_temp
    
    # ---- Stufe 2: Finales Image ----
      # ---- Stufe 2: Finales Image ----
FROM openjdk:17-jdk-slim

WORKDIR /opt/mustang

# Kopiere das kompilierte Ghostscript aus der Builder-Stufe
COPY --from=gs_builder /app/gs_install_temp/usr/local /usr/local/

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libcups2 \
        libfontconfig1 \
        libjpeg62-turbo \
        libpng16-16 \
        libtiff5 \
        zlib1g \
        libopenjp2-7 \
        libjbig2dec0 \
        libijs-0.35 \
        libidn11 \
        libpaper1 && \
    # ldconfig als separater Befehl nach der Installation ausführen
    echo "Aktualisiere Shared Library Cache..." && \
    ldconfig && \
    echo "Shared Library Cache aktualisiert." && \
    # Aufräumen
    rm -rf /var/lib/apt/lists/*

# Überprüfe die Ghostscript-Version im finalen Image
RUN echo "Installierte Ghostscript Version im finalen Image:" && gs --version
        
    
    # Installiere Python & Flask
    RUN apt-get update && \
        apt-get install -y --no-install-recommends \
            python3 \
            python3-pip \
        && pip3 install --no-cache-dir flask \
        && rm -rf /var/lib/apt/lists/*
    
    # MustangCLI kopieren
    COPY Mustang-CLI-2.16.4.jar ./Mustang-CLI-2.16.4.jar
    
    # ICC-Profil kopieren
    COPY sRGB.icc /opt/mustang/sRGB.icc
    
    # API-Service kopieren
    COPY api_service.py ./api_service.py
    
    # Port freigeben
    EXPOSE 8080
    
    # Startbefehl
    ENTRYPOINT ["python3", "/opt/mustang/api_service.py"]