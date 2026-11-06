#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
@interface EngineBridge : NSObject
+ (NSInteger)startAtRoot:(NSString *)root error:(NSError **)error NS_SWIFT_NAME(start(root:));
+ (BOOL)feedFlow:(NSString *)flow address:(NSString *)address port:(NSInteger)port direction:(NSString *)direction bytes:(NSData *)bytes error:(NSError **)error;
+ (BOOL)closeFlow:(NSString *)flow error:(NSError **)error;
+ (BOOL)stopWithError:(NSError **)error;
@end
NS_ASSUME_NONNULL_END
