from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

class EmailBackend(SMTPBackend):
    def open(self):
        """
        Ensure we can connect to the SMTP server.
        """
        if self.connection:
            return False

        try:
            self.connection = self.connection_class(self.host, self.port, timeout=self.timeout)
            self.connection.ehlo()
            if self.use_tls:
                self.connection.starttls()  # No keyfile or certfile arguments
                self.connection.ehlo()
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except Exception as e:
            if not self.fail_silently:
                raise
            return False