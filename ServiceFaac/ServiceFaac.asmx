<%@ WebService Language="C#"  Class="Consultas.Faac" %>



using System.Web.Services;
using System;
using System.Data;
using System.Data.OleDb;
using System.Xml.Serialization;
using System.Net;
using System.IO;
using System.Text;
using System.Diagnostics;


namespace Consultas
{
    /// <summary>
    /// Descripción breve del encriptor.
    /// </summary>
    [WebService(Namespace = "http://em-roll-fix/WebServices",
                Description = "Carga los datos y encripta el serial de una mochila")]

    public class Faac : System.Web.Services.WebService
    {
        public OleDbConnection myAccessConn = null;
        
        [WebMethod(Description = "Entrada de peticion")]
		
		public int EN_PE(string recibido)
		{
			int error = 0;

			string[] datos =
				recibido.Split(
					new char[] { '|' },
					4
				);

			if (datos.Length != 4)
				return 1;

			
			error = acceso_datos();

			if (error != 0)
				return 1;

			ReconstruirFicheroPeticion(ref datos);
			
			error = entrada_peticion(ref datos);

			if (error != 0)
				return 1;

			bool ok = EnviarAEnqueue(
				datos[1],
				datos[2],
				datos[3]
			);

			if (!ok)
				return 1;

			return 0;
		}

		[WebMethod(Description = "Entrada de claves")]
		public int EN_CL(string recibido)
		{
			if (String.IsNullOrWhiteSpace(recibido))
				return 1;

			/*
			 * Se limita a tres elementos para preservar íntegro
			 * ficheroClaves aunque contenga saltos de línea.
			 *
			 * datos[0] = licenceHex
			 * datos[1] = peticion
			 * datos[2] = ficheroClaves
			 */
			string[] datos = recibido.Split(
				new char[] { '|' },
				3
			);

			if (datos.Length != 3)
				return 1;

			datos[0] = (
				datos[0] ?? String.Empty
			).Trim().ToUpperInvariant();

			datos[1] = (
				datos[1] ?? String.Empty
			).Trim();

			if (
				datos[0].Length == 0 ||
				datos[1].Length == 0 ||
				String.IsNullOrWhiteSpace(datos[2])
			)
			{
				return 1;
			}

			int error = acceso_datos();

			if (error != 0)
				return 1;

			return entrada_claves(ref datos);
		}
        
        [WebMethod(Description = "Consulta resueltos")]
        public string CO_RS(string recibido) //Entrada de peticion
        {
            byte i;
            int error;
            string  respuesta = "0";
        
            error = acceso_datos();
            if (error == 0)
                respuesta = consulta_resueltos(recibido);

            return respuesta;

        }


        [WebMethod(Description = "consulta de peticiones")]
        public string CO_PE(string recibido) //Entrada de peticion
        {
            int error;
            string respuesta = "1";

            error = acceso_datos();
             if (error == 0)
                 respuesta = consulta_peticion();	

            return respuesta;

        }
        
        public int acceso_datos()
        {
            int error = 0;

            string strAccessConn = "Provider=Microsoft.Jet.OLEDB.4.0;Data Source=" + Server.MapPath(".") + "\\App_data\\Peticiones.mdb";


            // Create the dataset and add the Categories table to it:
            DataSet myDataSet = new DataSet();

            

            try
            {
                myAccessConn = new OleDbConnection(strAccessConn);

            }
            catch (Exception ex)
            {
                Console.WriteLine("Error: Failed to create a database connection. \n{0}", ex.Message);
                error = 1;
            }
            return error;
        }

        public int entrada_peticion(ref string[] datos)
        {
            int error = 0;
			Console.WriteLine("ENTRADA_PETICION INICIO");
			
            try
            {
                myAccessConn.Open();
                //  strAccessUpdate = "UPDATE Faac SET Faac.Cliente = @pepe";
                string  strAccessInsert = "INSERT INTO Faac (licence,licenceHex,peticion,recogida,procesada,cargada,ficheroPeticion,fecha)"+
                    " VALUES (@licence,@licenceHex,@peticion,@recogida,@procesada,@cargada,@ficheroPeticion,@fecha)";

                OleDbCommand myAccessCommand = new OleDbCommand(strAccessInsert, myAccessConn);
                myAccessCommand.Parameters.Add("@licence", OleDbType.Char).Value = datos[0];
                myAccessCommand.Parameters.Add("@licenceHex", OleDbType.Char).Value = datos[1];
                myAccessCommand.Parameters.Add("@peticion", OleDbType.Char).Value = datos[2];
                myAccessCommand.Parameters.Add("@recogida", OleDbType.Boolean).Value = false;
                myAccessCommand.Parameters.Add("@procesada", OleDbType.Boolean).Value = false;
                myAccessCommand.Parameters.Add("@cargada", OleDbType.Boolean).Value = true;
                myAccessCommand.Parameters.Add("@ficheroPeticion", OleDbType.LongVarWChar).Value = datos[3];
                myAccessCommand.Parameters.Add("@fecha", OleDbType.DBDate).Value = DateTime.Now;
				Console.WriteLine("ANTES DE INSERT");
                myAccessCommand.ExecuteNonQuery();
				Console.WriteLine("DESPUES DE INSERT");
                error = 0;

            }
            catch (Exception ex)
            {
                Console.WriteLine("ERROR entrada_peticion: " + ex.ToString());
                error = 1;
            }
            finally
            {

                myAccessConn.Close();
            }


            return error;

        }

        public string consulta_peticion()
        {
        
            string respuesta = "1";
	    string lic="";
            int licencia;
            int peticion;
            DataSet myDataSet = new DataSet();
            string strAccessSelect = "SELECT * FROM Faac WHERE cargada=false";
            string strAccessUpdate = "UPDATE Faac SET cargada=true WHERE licence=@licencia AND peticion=@peticion";
	    string strDeleteLicencia = "DELETE FROM Faac WHERE licence=@licencia"; 	    
	    try
            {

                OleDbCommand myAccessCommand = new OleDbCommand(strAccessSelect, myAccessConn);
                OleDbDataAdapter myDataAdapter = new OleDbDataAdapter(myAccessCommand);

                myAccessConn.Open();
                myDataAdapter.Fill(myDataSet, "Faac");

                DataRowCollection dra = myDataSet.Tables["Faac"].Rows;
                respuesta = dra[0][7].ToString();
                lic= dra[0][1].ToString();
                licencia = System.Int32.Parse(dra[0][1].ToString());
                peticion =  System.Int32.Parse(dra[0][3].ToString());
		myAccessCommand = new OleDbCommand(strAccessUpdate, myAccessConn);
                myAccessCommand.Parameters.Add("@licencia", OleDbType.Char).Value = licencia;
               	myAccessCommand.Parameters.Add("@peticion", OleDbType.Char).Value = peticion;             
                myAccessCommand.ExecuteNonQuery();
	    }

            catch (System.OverflowException)
	    {
		OleDbCommand myAccessCommand = new OleDbCommand(strDeleteLicencia, myAccessConn);
      		myAccessCommand.Parameters.AddWithValue("@licencia",lic);              
		myAccessCommand.ExecuteNonQuery();
                	
            }
                
            catch (Exception ex)
            {
                Console.WriteLine("Error: Failed to retrieve the required data from the DataBase.\n{0}", ex.Message);
                respuesta = "1";
            }
            finally
            {

               myAccessConn.Close();
            }
	

            return respuesta;
        }

        

        public string consulta_resueltos(string recibido)
        {
            string respuesta = "1";
            int licencia;
            int peticion;
            DataSet myDataSet = new DataSet();
            string strAccessSelect = "SELECT * FROM Faac WHERE procesada=true AND recogida=false AND licence=@licencia";
            string strAccessUpdate = "UPDATE Faac SET recogida=true WHERE licence=@licencia AND procesada=true AND peticion=@peticion";
            try
            {

                OleDbCommand myAccessCommand = new OleDbCommand(strAccessSelect, myAccessConn);
                myAccessCommand.Parameters.Add("@licencia", OleDbType.Char).Value = recibido;
                OleDbDataAdapter myDataAdapter = new OleDbDataAdapter(myAccessCommand);
                
                myAccessConn.Open();
                myDataAdapter.Fill(myDataSet, "Faac");

                DataRowCollection dra = myDataSet.Tables["Faac"].Rows;
                respuesta = dra[0][8].ToString();
                peticion = System.Int32.Parse(dra[0][3].ToString());

                myAccessCommand = new OleDbCommand(strAccessUpdate, myAccessConn);
                myAccessCommand.Parameters.Add("@licencia", OleDbType.Char).Value = recibido;
                myAccessCommand.Parameters.Add("@peticion", OleDbType.Char).Value = peticion;
                myAccessCommand.ExecuteNonQuery();

            }
            catch (Exception ex)
            {
                Console.WriteLine("Error: Failed to retrieve the required data from the DataBase.\n{0}", ex.Message);
                respuesta = "1";
            }
            finally
            {

                myAccessConn.Close();
            }

            return respuesta;
        }

        public int entrada_claves(ref string[] datos)
		{
			if (datos == null || datos.Length != 3)
				return 1;

			try
			{
				string strAccessUpdate =
					"UPDATE Faac SET " +
					"ficheroClaves=?, " +
					"procesada=true " +
					"WHERE licenceHex=? " +
					"AND peticion=? " +
					"AND cargada=true " +
					"AND recogida=false";

				myAccessConn.Open();

				using (OleDbCommand command =
					new OleDbCommand(
						strAccessUpdate,
						myAccessConn
					))
				{
					/*
					 * OleDb asocia los parámetros por posición.
					 * Deben añadirse en el mismo orden de los ?.
					 */

					command.Parameters.Add(
						"p1",
						OleDbType.LongVarWChar
					).Value = datos[2];

					command.Parameters.Add(
						"p2",
						OleDbType.Char
					).Value = datos[0];

					command.Parameters.Add(
						"p3",
						OleDbType.Char
					).Value = datos[1];

					int filasActualizadas =
						command.ExecuteNonQuery();

					/*
					 * EN_CL solo es correcto si actualiza
					 * exactamente el registro correspondiente.
					 */
					if (filasActualizadas != 1)
					{
						Trace.WriteLine(
							"EN_CL: filas actualizadas=" +
							filasActualizadas.ToString() +
							", licenceHex=" + datos[0] +
							", peticion=" + datos[1]
						);

						return 1;
					}
				}

				return 0;
			}
			catch (Exception ex)
			{
				Trace.WriteLine(
					"entrada_claves ERROR: " +
					ex.ToString()
				);

				return 1;
			}
			finally
			{
				if (
					myAccessConn != null &&
					myAccessConn.State !=
						ConnectionState.Closed
				)
				{
					myAccessConn.Close();
				}
			}
		}
		
		private bool EnviarAEnqueue(
			string licencia,
			string peticion,
			string ficheroPeticion)
		{
			try
			{
				string json =
				"{"
				+ "\"licencia\":\"" + EscaparJson(licencia) + "\","
				+ "\"peticion\":" + peticion + ","
				+ "\"fichero_peticion\":\""
				+ EscaparJson(ficheroPeticion)
				+ "\""
				+ "}";
				

				byte[] data =
					Encoding.UTF8.GetBytes(json);

				HttpWebRequest request =
					(HttpWebRequest)WebRequest.Create(
						"http://localhost:8011/enqueue"
					);

				request.Method = "POST";
				request.ContentType =
					"application/json";

				request.Timeout = 10000;

				using (Stream stream =
					request.GetRequestStream())
				{
					stream.Write(
						data,
						0,
						data.Length
					);
				}

				using (HttpWebResponse response =
					(HttpWebResponse)
						request.GetResponse())
				{
					return (
						response.StatusCode ==
						HttpStatusCode.Created
						||
						response.StatusCode ==
						HttpStatusCode.OK
					);
				}
			}
			catch (Exception ex)
			{
				Trace.WriteLine(
					"Error /enqueue: "
					+ ex.Message
				);

				return false;
			}
		}
		
		private string EscaparJson(string valor)
		{
			if (valor == null)
				return String.Empty;

			StringBuilder resultado = new StringBuilder();

			foreach (char caracter in valor)
			{
				switch (caracter)
				{
					case '\\':
						resultado.Append("\\\\");
						break;

					case '"':
						resultado.Append("\\\"");
						break;

					case '\r':
						resultado.Append("\\r");
						break;

					case '\n':
						resultado.Append("\\n");
						break;

					case '\t':
						resultado.Append("\\t");
						break;

					default:
						if (caracter < 32)
						{
							resultado.Append(
								"\\u" + ((int)caracter)
							);
						}	
						else
						{
							resultado.Append(caracter);
						}
						break;
				}
			}

			return resultado.ToString();
		
		}
		
		private void ReconstruirFicheroPeticion(
			ref string[] datos)
		{
			string[] tokens =
				datos[3].Split(
					new char[] { ' ' },
					StringSplitOptions.RemoveEmptyEntries
				);

			StringBuilder sb =
				new StringBuilder();

			sb.Append(tokens[0]);
			sb.Append(" ");
			sb.Append(tokens[1]);

			int i = 2;

			while (i < tokens.Length)
			{
				if (tokens[i].StartsWith("Button"))
				{
					sb.Append("\r\n");
					sb.Append(tokens[i]);
					sb.Append("\r\n");

					for (int j = 1; j <= 4; j++)
					{
						if (i + j < tokens.Length)
						{
							sb.Append(tokens[i + j]);
							sb.Append("\r\n");
						}
					}

					i += 5;
				}
				else
				{
					i++;
				}
			}

			datos[3] = sb.ToString();
		}
		
	}

}
