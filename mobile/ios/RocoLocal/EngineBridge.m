#import "EngineBridge.h"
#import <Python/Python.h>

static PyObject *backend;

static void bridgeError(NSError **error, NSString *message) {
    if (error) *error = [NSError errorWithDomain:@"RocoPython" code:1
        userInfo:@{NSLocalizedDescriptionKey: message}];
}

static void pythonError(NSError **error) {
    PyObject *exception = PyErr_GetRaisedException();
    PyObject *description = exception ? PyObject_Str(exception) : NULL;
    const char *text = description ? PyUnicode_AsUTF8(description) : NULL;
    bridgeError(error, text ? [NSString stringWithUTF8String:text] : @"本机引擎调用失败");
    Py_XDECREF(description);
    Py_XDECREF(exception);
    PyErr_Clear();
}

static BOOL appendPath(PyConfig *config, NSString *path) {
    wchar_t *wide = Py_DecodeLocale(path.fileSystemRepresentation, NULL);
    if (!wide) return NO;
    PyStatus result = PyWideStringList_Append(&config->module_search_paths, wide);
    PyMem_RawFree(wide);
    return !PyStatus_Exception(result);
}

@implementation EngineBridge
+ (NSInteger)startAtRoot:(NSString *)root error:(NSError **)error {
    @synchronized(self) {
        if (!Py_IsInitialized()) {
            NSString *bundle = NSBundle.mainBundle.resourcePath;
            PyPreConfig pre;
            PyPreConfig_InitIsolatedConfig(&pre);
            pre.utf8_mode = 1;
            PyStatus status = Py_PreInitialize(&pre);
            if (PyStatus_Exception(status)) {
                bridgeError(error, @"Python 预初始化失败"); return 0;
            }
            PyConfig config;
            PyConfig_InitIsolatedConfig(&config);
            config.buffered_stdio = 0;
            config.write_bytecode = 0;
            // Initialization runs on the engine queue, outside the main thread.
            config.install_signal_handlers = 0;
            config.module_search_paths_set = 1;
            status = PyConfig_SetBytesString(&config, &config.home,
                [[bundle stringByAppendingPathComponent:@"python"] fileSystemRepresentation]);
            BOOL pathsOK = appendPath(&config, [bundle stringByAppendingPathComponent:@"python/lib/python3.13"])
                && appendPath(&config, [bundle stringByAppendingPathComponent:@"python/lib/python3.13/lib-dynload"])
                && appendPath(&config, [bundle stringByAppendingPathComponent:@"engine"])
                && appendPath(&config, [bundle stringByAppendingPathComponent:@"app_packages"]);
            if (!PyStatus_Exception(status) && pathsOK) status = Py_InitializeFromConfig(&config);
            BOOL failed = PyStatus_Exception(status) || !pathsOK;
            PyConfig_Clear(&config);
            if (failed) { bridgeError(error, @"Python 3.13 初始化失败；请检查 iOS 运行库和标准库"); return 0; }
            PyEval_SaveThread();
        }
        PyGILState_STATE gil = PyGILState_Ensure();
        if (!backend) {
            PyObject *bootstrap = PyImport_ImportModule("roco_ios_bootstrap");
            if (bootstrap) {
                Py_DECREF(bootstrap);
                backend = PyImport_ImportModule("roco_mobile");
            }
        }
        PyObject *result = backend ? PyObject_CallMethod(backend, "start", "s", root.UTF8String) : NULL;
        long port = result ? PyLong_AsLong(result) : 0;
        if (!result || PyErr_Occurred()) { pythonError(error); port = 0; }
        if (result && (port < 1 || port > 65535)) { bridgeError(error, @"本机引擎没有返回有效端口"); port = 0; }
        Py_XDECREF(result);
        PyGILState_Release(gil);
        return port;
    }
}

+ (BOOL)feedFlow:(NSString *)flow address:(NSString *)address port:(NSInteger)port direction:(NSString *)direction bytes:(NSData *)bytes error:(NSError **)error {
    @synchronized(self) {
        if (!backend || !Py_IsInitialized()) { bridgeError(error, @"本机引擎未启动"); return NO; }
        if (port < 1 || port > 65535 || bytes.length == 0 || bytes.length > 65536) {
            bridgeError(error, @"无效的有序数据流"); return NO;
        }
        PyGILState_STATE gil = PyGILState_Ensure();
        PyObject *chunk = PyBytes_FromStringAndSize(bytes.bytes, (Py_ssize_t)bytes.length);
        PyObject *result = chunk ? PyObject_CallMethod(backend, "feed", "sslsO",
            flow.UTF8String, address.UTF8String, (long)port, direction.UTF8String, chunk) : NULL;
        int accepted = result ? PyObject_IsTrue(result) : -1;
        if (accepted < 0) pythonError(error);
        else if (!accepted) bridgeError(error, @"解码器拒绝数据；停止采集后重新连接");
        Py_XDECREF(result);
        Py_XDECREF(chunk);
        PyGILState_Release(gil);
        return accepted > 0;
    }
}

+ (BOOL)closeFlow:(NSString *)flow error:(NSError **)error {
    @synchronized(self) {
        if (!backend || !Py_IsInitialized()) { bridgeError(error, @"本机引擎未启动"); return NO; }
        PyGILState_STATE gil = PyGILState_Ensure();
        PyObject *result = PyObject_CallMethod(backend, "close_flow", "s", flow.UTF8String);
        int accepted = result ? PyObject_IsTrue(result) : -1;
        if (accepted < 0) pythonError(error);
        Py_XDECREF(result);
        PyGILState_Release(gil);
        return accepted > 0;
    }
}

+ (BOOL)stopWithError:(NSError **)error {
    @synchronized(self) {
        if (!backend || !Py_IsInitialized()) return YES;
        PyGILState_STATE gil = PyGILState_Ensure();
        PyObject *result = PyObject_CallMethod(backend, "stop", NULL);
        BOOL stopped = result != NULL;
        if (!stopped) pythonError(error);
        Py_XDECREF(result);
        PyGILState_Release(gil);
        // Keep the interpreter alive: finalizing while Python workers exist is unsafe.
        return stopped;
    }
}
@end
