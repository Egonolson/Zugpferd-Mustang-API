# ---- Stage 1: Ghostscript Builder ----
FROM debian:bullseye AS gs_builder

# Ghostscript version to build
ARG GS_VERSION=10.05.1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates curl build-essential tar pkg-config \
      zlib1g-dev libpng-dev libjpeg62-turbo-dev libtiff5-dev \
      libcups2-dev libfontconfig1-dev libidn11-dev libpaper-dev \
      libijs-dev libjbig2dec0-dev libopenjp2-7-dev && \
    update-ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src

# Download Ghostscript sources from official GitHub release assets
RUN set -eux; \
    GS_TAG="$(echo "${GS_VERSION}" | awk -F. '{printf \"gs%d%02d%d\", $1,$2,$3}')"; \
    curl -fsSL -o ghostscript_archive.tar.gz \
      "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/${GS_TAG}/ghostscript-${GS_VERSION}.tar.gz"; \
    tar -xzf ghostscript_archive.tar.gz; \
    rm ghostscript_archive.tar.gz

WORKDIR /usr/src/ghostscript-${GS_VERSION}
RUN ./configure \
      --prefix=/usr/local \
      --disable-compile-inits \
      --disable-gtk \
      --without-x \
      --with-ijs \
      --with-jbig2dec \
      --with-openjpeg \
    && make -j"$(nproc)" \
    && make install DESTDIR=/app/gs_install_temp

# ---- Stage 2: Mustang Builder (Build-Time Latest) ----
# Builds Mustang-CLI from the latest GitHub release tag (core-x.y.z) using JDK 21 + Maven.
FROM maven:3.9.6-eclipse-temurin-21 AS mustang_builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl jq ca-certificates && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ARG MUSTANG_REPO=https://github.com/ZUGFeRD/mustangproject.git
ARG MUSTANG_TAG=latest

WORKDIR /build

RUN set -eux; \
    if [ "${MUSTANG_TAG}" = "latest" ]; then \
      TAG="$(curl -fsSL https://api.github.com/repos/ZUGFeRD/mustangproject/releases/latest | jq -r '.tag_name')"; \
    else \
      TAG="${MUSTANG_TAG}"; \
    fi; \
    echo "Resolved Mustang tag: ${TAG}"; \
    mkdir -p /out; \
    printf "%s\n" "${TAG}" > /out/mustang_tag.txt; \
    git clone --depth 1 --branch "${TAG}" "${MUSTANG_REPO}" /src; \
    cd /src; \
    mvn -DskipTests -pl Mustang-CLI -am clean package; \
    cp /src/Mustang-CLI/target/Mustang-CLI-*.jar /out/Mustang-CLI.jar; \
    java -jar /out/Mustang-CLI.jar --help | tee /out/mustang_help.txt; \
    grep -q "metrics|combine" /out/mustang_help.txt; \
    grep -q "|validate" /out/mustang_help.txt

# ---- Stage 3: Final image ----
# Keep Debian bullseye runtime to match Ghostscript's runtime library expectations.
FROM debian:bullseye-slim

ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="$JAVA_HOME/bin:${PATH}"

WORKDIR /opt/mustang

# Ghostscript from stage 1
COPY --from=gs_builder /app/gs_install_temp/usr/local /usr/local/

# Runtime deps (Java comes from mustang_builder stage; no apt OpenJDK required)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      python3 python3-pip \
      libcups2 libfontconfig1 libjpeg62-turbo libpng16-16 libtiff5 zlib1g \
      libopenjp2-7 libjbig2dec0 libijs-0.35 libidn11 libpaper1 \
      icc-profiles-free curl \
    && update-ca-certificates \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip3 install --no-cache-dir flask==3.0.3 werkzeug==3.0.3

# Java 21 runtime from builder (Temurin)
COPY --from=mustang_builder /opt/java/openjdk /opt/java/openjdk
RUN ln -sf "$JAVA_HOME/bin/java" /usr/bin/java

# Mustang CLI (built from GitHub repo at build time)
COPY --from=mustang_builder /out/Mustang-CLI.jar /opt/mustang/Mustang-CLI.jar
COPY --from=mustang_builder /out/mustang_tag.txt /opt/mustang/mustang_tag.txt
COPY --from=mustang_builder /out/mustang_help.txt /opt/mustang/mustang_help.txt

COPY sRGB.icc /opt/mustang/sRGB.icc
COPY api_service.py /opt/mustang/api_service.py

EXPOSE 8080
ENV PYTHONUNBUFFERED=1

CMD ["python3", "/opt/mustang/api_service.py"]
