import {WebView} from '@amazon-devices/webview';
import * as React from 'react';
import {View, StyleSheet} from 'react-native';
import {
  useHideSplashScreenCallback,
  usePreventHideSplashScreen,
} from '@amazon-devices/react-native-kepler';
import {
  SslErrorData,
  WebViewErrorEvent,
  WebViewHttpErrorEvent,
  WebViewNavigationEvent,
} from '@amazon-devices/webview/dist/types/WebViewTypes';

export const App = () => {
  // By default splash screen is shown in app launch, as the splash
  // screen images are bundled in this app (assets/raw/ folder)
  // Declare that application wants to extend splash screen lifecycle
  usePreventHideSplashScreen();
  const hideSplashScreenCallback = useHideSplashScreenCallback();
  return (
    <View style={styles.container}>
      <WebView
        style={styles.webview}
        allowSystemKeyEvents
        allowsDefaultMediaControl
        domStorageEnabled
        hasTVPreferredFocus
        javaScriptEnabled
        mediaPlaybackRequiresUserAction={false}
        mixedContentMode="never"
        // thirdPartyCookiesEnabled
        // userAgent={''}
        source={{
          // headers: {},
          uri: 'http://127.0.0.1:8300/tv?play=park_chase',
        }}
        onLoad={(_event: WebViewNavigationEvent) => {
          console.info('Page loading completed...');
          // Hide the splash screen
          hideSplashScreenCallback();
        }}
        onLoadStart={(_event: WebViewNavigationEvent) => {
          console.info('Page loading started...');
        }}
        onError={({
          nativeEvent: {code},
        }: WebViewErrorEvent) => {
          hideSplashScreenCallback();
          console.error(`HomeBound page unavailable (${code})`);
        }}
        onHttpError={({
          nativeEvent: {statusCode: code, isMainFrame},
        }: WebViewHttpErrorEvent) => {
          if (isMainFrame) hideSplashScreenCallback();
          console.error(`HomeBound HTTP error (${code})`);
        }}
        onSslError={({code}: SslErrorData) => {
          hideSplashScreenCallback();
          console.error(`HomeBound TLS error (${code})`);
        }}
      />
    </View>
  );
};

// Styles for layout, which are necessary for proper focus behavior
const styles = StyleSheet.create({
  container: {flex: 1},
  webview: {flex: 1, backgroundColor: '#000000'},
});
