"""Generate the checked-in Xcode project using only Python's standard library."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
objects = {}


def uid(name):
    return hashlib.sha256(name.encode()).hexdigest()[:24].upper()


def obj(identity, isa, **values):
    key = uid(identity)
    objects[key] = {"isa": isa, **values}
    return key


def ref(path, kind):
    return obj("file:" + path, "PBXFileReference", lastKnownFileType=kind, path=path, sourceTree="<group>")


def build(name, file, **extras):
    return obj("build:" + name, "PBXBuildFile", fileRef=file, **extras)


def config(name, settings):
    return obj("config:" + name, "XCBuildConfiguration", name=name.rsplit(":", 1)[-1], buildSettings=settings)


def configs(name, settings):
    return obj("configs:" + name, "XCConfigurationList", buildConfigurations=[
        config(name + ":Debug", dict(settings, SWIFT_OPTIMIZATION_LEVEL="-Onone", DEBUG_INFORMATION_FORMAT="dwarf")),
        config(name + ":Release", dict(settings, SWIFT_OPTIMIZATION_LEVEL="-O", DEBUG_INFORMATION_FORMAT="dwarf-with-dsym"))
    ], defaultConfigurationIsVisible=0, defaultConfigurationName="Release")


def encode(value, depth=0):
    if isinstance(value, dict):
        return "{\n" + "".join("\t" * (depth + 1) + json.dumps(k) + " = " + encode(v, depth + 1) + ";\n"
            for k, v in value.items()) + "\t" * depth + "}"
    if isinstance(value, list):
        return "(" + ", ".join(encode(v, depth + 1) for v in value) + ")"
    return str(value) if isinstance(value, int) else json.dumps(value)


def main():
    app_sources = [ref("RocoLocal/" + name, kind) for name, kind in [
        ("RocoLocalApp.swift", "sourcecode.swift"), ("HUDPreview.swift", "sourcecode.swift"),
        ("EngineBridge.m", "sourcecode.c.objc")]]
    headers = [ref("RocoLocal/" + name, "sourcecode.c.h") for name in ("EngineBridge.h", "BridgingHeader.h")]
    extension_source = ref("PacketTunnel/PacketTunnelProvider.swift", "sourcecode.swift")
    python = ref("Runtime/Python.xcframework", "wrapper.xcframework")
    app_product = obj("product:app", "PBXFileReference", explicitFileType="wrapper.application",
        path="RocoLocal.app", sourceTree="BUILT_PRODUCTS_DIR", includeInIndex=0)
    tunnel_product = obj("product:tunnel", "PBXFileReference", explicitFileType="wrapper.app-extension",
        path="PacketTunnel.appex", sourceTree="BUILT_PRODUCTS_DIR", includeInIndex=0)
    products = obj("products", "PBXGroup", name="Products", sourceTree="<group>", children=[app_product, tunnel_product])
    source_files = app_sources + headers + [extension_source, python]
    source_files += [ref(name, "text.plist.xml") for name in ["RocoLocal/Info.plist", "RocoLocal/RocoLocal.entitlements",
        "PacketTunnel/Info.plist", "PacketTunnel/PacketTunnel.entitlements"]]
    group = obj("mainGroup", "PBXGroup", sourceTree="<group>", children=source_files + [products])
    app_build = obj("sources:app", "PBXSourcesBuildPhase", buildActionMask=2147483647,
        files=[build(path, path) for path in app_sources], runOnlyForDeploymentPostprocessing=0)
    tunnel_build = obj("sources:tunnel", "PBXSourcesBuildPhase", buildActionMask=2147483647,
        files=[build("tunnel", extension_source)], runOnlyForDeploymentPostprocessing=0)
    link = obj("frameworks:app", "PBXFrameworksBuildPhase", buildActionMask=2147483647,
        files=[build("python-link", python)], runOnlyForDeploymentPostprocessing=0)
    runtime = obj("install-python", "PBXShellScriptBuildPhase", buildActionMask=2147483647,
        name="Install and sign target Python modules", files=[], inputPaths=[], outputPaths=[],
        shellPath="/bin/sh", shellScript='set -eu\n/usr/bin/env python3 "$PROJECT_DIR/scripts/install-python.py"\n',
        alwaysOutOfDate=1, runOnlyForDeploymentPostprocessing=0)
    embed = obj("embed-python", "PBXCopyFilesBuildPhase", buildActionMask=2147483647,
        name="Embed Python", dstPath="", dstSubfolderSpec=10,
        files=[build("python-embed", python, settings={"ATTRIBUTES": ["CodeSignOnCopy", "RemoveHeadersOnCopy"]})],
        runOnlyForDeploymentPostprocessing=0)
    project_settings = {"IPHONEOS_DEPLOYMENT_TARGET": "16.0", "SDKROOT": "iphoneos",
        "SWIFT_VERSION": "5.0", "CLANG_ENABLE_MODULES": "YES", "CLANG_ENABLE_OBJC_ARC": "YES",
        "ENABLE_USER_SCRIPT_SANDBOXING": "NO", "TARGETED_DEVICE_FAMILY": "1,2", "CODE_SIGN_STYLE": "Automatic"}
    app_settings = {"PRODUCT_BUNDLE_IDENTIFIER": "cn.roco.local", "PRODUCT_NAME": "$(TARGET_NAME)",
        "INFOPLIST_FILE": "RocoLocal/Info.plist", "SWIFT_OBJC_BRIDGING_HEADER": "RocoLocal/BridgingHeader.h",
        "FRAMEWORK_SEARCH_PATHS": ["$(inherited)", "$(PROJECT_DIR)/Runtime"],
        "HEADER_SEARCH_PATHS": ["$(inherited)", "$(BUILT_PRODUCTS_DIR)/Python.framework/Headers"],
        "LD_RUNPATH_SEARCH_PATHS": ["$(inherited)", "@executable_path/Frameworks"],
        "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator", "SUPPORTS_MACCATALYST": "NO"}
    tunnel_settings = {"PRODUCT_BUNDLE_IDENTIFIER": "cn.roco.local.PacketTunnel", "PRODUCT_NAME": "$(TARGET_NAME)",
        "INFOPLIST_FILE": "PacketTunnel/Info.plist", "CODE_SIGN_ENTITLEMENTS": "PacketTunnel/PacketTunnel.entitlements",
        "APPLICATION_EXTENSION_API_ONLY": "YES", "SKIP_INSTALL": "YES", "LD_RUNPATH_SEARCH_PATHS": [
            "$(inherited)", "@executable_path/Frameworks", "@executable_path/../../Frameworks"]}
    app = obj("target:app", "PBXNativeTarget", name="RocoLocal", productName="RocoLocal", productReference=app_product,
        productType="com.apple.product-type.application", buildConfigurationList=configs("app", app_settings),
        buildPhases=[app_build, link, runtime, embed], buildRules=[], dependencies=[])
    tunnel = obj("target:tunnel", "PBXNativeTarget", name="PacketTunnel", productName="PacketTunnel", productReference=tunnel_product,
        productType="com.apple.product-type.app-extension", buildConfigurationList=configs("tunnel", tunnel_settings),
        buildPhases=[tunnel_build], buildRules=[], dependencies=[])
    project = obj("project", "PBXProject", attributes={"LastUpgradeCheck": "1600"},
        buildConfigurationList=configs("project", project_settings), compatibilityVersion="Xcode 14.0",
        developmentRegion="zh_CN", knownRegions=["zh_CN", "en", "Base"], mainGroup=group,
        productRefGroup=products, projectDirPath="", projectRoot="", targets=[app, tunnel])
    destination = ROOT / "RocoLocal.xcodeproj"
    destination.mkdir(exist_ok=True)
    data = {"archiveVersion": 1, "classes": {}, "objectVersion": 56, "objects": objects, "rootObject": project}
    (destination / "project.pbxproj").write_text("// !$*UTF8*$!\n" + encode(data) + "\n", encoding="utf8")
    schemes = destination / "xcshareddata/xcschemes"
    schemes.mkdir(parents=True, exist_ok=True)
    for name, target, product in [("RocoLocal", app, "RocoLocal.app"), ("PacketTunnel", tunnel, "PacketTunnel.appex")]:
        reference = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="{product}" BlueprintName="{name}" ReferencedContainer="container:RocoLocal.xcodeproj"/>'
        launch = f'<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB"><BuildableProductRunnable runnableDebuggingMode="0">{reference}</BuildableProductRunnable></LaunchAction>' if name == "RocoLocal" else ""
        (schemes / (name + ".xcscheme")).write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<Scheme LastUpgradeVersion="1600" version="1.3"><BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{reference}</BuildActionEntry></BuildActionEntries></BuildAction>{launch}<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/></Scheme>\n', encoding="utf8")
    print("Generated RocoLocal.xcodeproj (foreground app and separate fail-closed extension targets).")


if __name__ == "__main__":
    main()
